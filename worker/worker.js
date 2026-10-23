// grokkius-fleet watch Worker (Cloudflare Workers, free plan).
// GET /health          -> {ok:true}
// GET /watch[?fresh=1] -> compact bounty digest (Bearer FLEET_TOKEN required)
// Cron trigger refreshes the digest into KV so /watch is a cheap KV read.
// Secrets (set with `wrangler secret put`, never in this repo): FLEET_TOKEN, SUPERTEAM_KEY.
// Optional KV binding: FLEET_KV.
// Drafted by Groq gpt-oss-120b via ai-job (fleet-worker-1023b); reviewed/fixed by Sir Grokkius (AI):
// Cache API is a no-op on workers.dev, so caching moved to KV; Cache.put has no TTL option;
// ids namespaced per source; seen-set capped; digest-based constant-time token compare.

const TTL_S = 900;
const SEEN_CAP = 2000;

const json = (obj, status = 200) =>
  new Response(JSON.stringify(obj), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
  });

async function sha(s) {
  return new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s)));
}

export async function tokenOk(given, expected) {
  if (!expected) return false;
  const [a, b] = await Promise.all([sha(given), sha(expected)]);
  let d = 0;
  for (let i = 0; i < a.length; i++) d |= a[i] ^ b[i];
  return d === 0;
}

async function getJSON(url, headers = {}) {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), 8000);
  try {
    const r = await fetch(url, {
      headers: { "user-agent": "grokkius-fleet-watch/1.0", accept: "application/json", ...headers },
      signal: ctl.signal,
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return await r.json();
  } finally {
    clearTimeout(t);
  }
}

const day = (v) => (typeof v === "string" && v.length >= 10 ? v.slice(0, 10) : null);

export async function buildDigest(env, now = new Date()) {
  const sources = {};
  const items = [];
  const jobs = [];
  if (env.SUPERTEAM_KEY) {
    jobs.push(
      (async () => {
        const url = `https://superteam.fun/api/agents/listings/live?take=50&deadline=${now.toISOString().slice(0, 10)}`;
        const j = await getJSON(url, { authorization: `Bearer ${env.SUPERTEAM_KEY}` });
        const list = Array.isArray(j) ? j : j.listings || j.data || [];
        for (const l of list) {
          if (!l || !l.slug) continue;
          items.push({
            id: `superteam:${l.slug}`, src: "superteam", title: String(l.title || "").slice(0, 120),
            reward: l.rewardAmount ?? null, token: l.token ?? null, deadline: day(l.deadline),
            access: l.agentAccess ?? null, url: `https://superteam.fun/earn/listing/${l.slug}`,
          });
        }
        return ["superteam", list.length];
      })().catch((e) => ["superteam", null, String(e.message || e).slice(0, 80)])
    );
  } else {
    sources.superteam = { ok: false, count: 0, error: "no key configured" };
  }
  jobs.push(
    (async () => {
      const j = await getJSON("https://www.task-bounty.com/api/v1/tasks");
      const list = (j && j.data) || [];
      for (const t of list) {
        if (!t || t.id == null) continue;
        items.push({
          id: `taskbounty:${t.id}`, src: "taskbounty", title: String(t.title || "").slice(0, 120),
          reward: typeof t.bounty_cents === "number" ? t.bounty_cents / 100 : null, token: "USD",
          deadline: day(t.deadline), access: null, url: t.github_issue_url || "https://www.task-bounty.com/",
        });
      }
      return ["taskbounty", list.length];
    })().catch((e) => ["taskbounty", null, String(e.message || e).slice(0, 80)])
  );
  for (const [name, count, error] of await Promise.all(jobs)) {
    sources[name] = error ? { ok: false, count: 0, error } : { ok: true, count };
  }
  items.sort((a, b) => a.id.localeCompare(b.id));
  return { generated_utc: now.toISOString().replace(/\.\d+Z$/, "Z"), sources, items };
}

export async function refresh(env, now = new Date()) {
  const digest = await buildDigest(env, now);
  digest.new = [];
  if (env.FLEET_KV) {
    const seen = JSON.parse((await env.FLEET_KV.get("watch:seen")) || "[]");
    const s = new Set(seen);
    for (const it of digest.items) if (!s.has(it.id)) { digest.new.push(it.id); seen.push(it.id); s.add(it.id); }
    await env.FLEET_KV.put("watch:seen", JSON.stringify(seen.slice(-SEEN_CAP)));
    await env.FLEET_KV.put("watch:last", JSON.stringify(digest));
  }
  return digest;
}

export default {
  async fetch(request, env) {
    const u = new URL(request.url);
    if (request.method !== "GET") return json({ error: "method not allowed" }, 405);
    if (u.pathname === "/health") return json({ ok: true, ts: new Date().toISOString() });
    if (u.pathname !== "/watch") return json({ error: "not found" }, 404);
    const auth = request.headers.get("authorization") || "";
    const given = auth.startsWith("Bearer ") ? auth.slice(7).trim() : "";
    if (!(await tokenOk(given, env.FLEET_TOKEN || ""))) return json({ error: "unauthorized" }, 401);
    if (env.FLEET_KV && u.searchParams.get("fresh") !== "1") {
      const last = await env.FLEET_KV.get("watch:last");
      if (last) {
        const d = JSON.parse(last);
        if (Date.now() - Date.parse(d.generated_utc) < TTL_S * 1000) return json({ ...d, cached: true });
      }
    }
    return json(await refresh(env));
  },
  async scheduled(_event, env, ctx) {
    ctx.waitUntil(refresh(env));
  },
};
