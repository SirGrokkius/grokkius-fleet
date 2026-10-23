// grokkius-fleet watcher: Cloudflare Worker (free plan). Fetches public bounty
// listings and returns one compact JSON digest so the home box needs one call.
// Draft by openai/gpt-oss-120b (via Groq, ai-job fleet-worker-1023b); reviewed,
// fixed and tested by Sir Grokkius (AI agent). Secrets live only in Worker
// secrets (FLEET_TOKEN, SUPERTEAM_KEY), never in this repo.
const CACHE_KEY = "https://fleet.cache/watch";
const TTL = 900; // 15 min
const SEEN_MAX = 500;

const json = (obj, status = 200, extra = {}) =>
  new Response(JSON.stringify(obj), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", ...extra },
  });

export default {
  async fetch(request, env, ctx) {
    const u = new URL(request.url);
    if (request.method !== "GET") return json({ error: "not found" }, 404);
    if (u.pathname === "/health") return json({ ok: true, ts: new Date().toISOString() });
    if (u.pathname !== "/watch") return json({ error: "not found" }, 404);

    const auth = request.headers.get("authorization") || "";
    const given = auth.startsWith("Bearer ") ? auth.slice(7).trim() : "";
    if (!env.FLEET_TOKEN || !safeEqual(given, String(env.FLEET_TOKEN))) {
      return json({ error: "unauthorized" }, 401);
    }

    const cache = caches.default;
    const key = new Request(CACHE_KEY);
    if (u.searchParams.get("fresh") !== "1") {
      const hit = await cache.match(key);
      if (hit) return hit;
    }
    const digest = await buildDigest(env);
    await remember(env, digest);
    const resp = json(digest, 200, { "cache-control": `max-age=${TTL}` });
    ctx.waitUntil(cache.put(key, resp.clone()));
    return resp;
  },

  async scheduled(event, env, ctx) {
    const digest = await buildDigest(env);
    await remember(env, digest);
    ctx.waitUntil(
      caches.default.put(new Request(CACHE_KEY), json(digest, 200, { "cache-control": `max-age=${TTL}` }))
    );
  },
};

function safeEqual(a, b) {
  // constant-time over the longer length; length mismatch still fails
  const n = Math.max(a.length, b.length);
  let r = a.length ^ b.length;
  for (let i = 0; i < n; i++) r |= (a.charCodeAt(i) || 0) ^ (b.charCodeAt(i) || 0);
  return r === 0;
}

async function remember(env, digest) {
  if (!env.FLEET_KV) return;
  const raw = await env.FLEET_KV.get("watch:seen");
  let seen = [];
  try { seen = raw ? JSON.parse(raw) : []; } catch { seen = []; }
  const set = new Set(seen);
  digest.new = digest.items.map((i) => i.id).filter((id) => id && !set.has(id));
  if (digest.new.length) {
    const merged = [...seen, ...digest.new].slice(-SEEN_MAX);
    await env.FLEET_KV.put("watch:seen", JSON.stringify(merged));
  }
  await env.FLEET_KV.put("watch:last", JSON.stringify(digest));
}

async function getJSON(url, headers = {}) {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), 8000);
  try {
    const r = await fetch(url, { headers: { "user-agent": "grokkius-fleet/1.0", ...headers }, signal: ctl.signal });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return await r.json();
  } finally {
    clearTimeout(t);
  }
}

async function source(name, sources, items, fn) {
  try {
    const got = await fn();
    items.push(...got);
    sources[name] = { ok: true, count: got.length };
  } catch (e) {
    sources[name] = { ok: false, count: 0, error: String(e && e.message || e).slice(0, 120) };
  }
}

export async function buildDigest(env) {
  const now = new Date();
  const sources = {};
  const items = [];
  const jobs = [];
  if (env.SUPERTEAM_KEY) {
    jobs.push(source("superteam", sources, items, async () => {
      const day = now.toISOString().slice(0, 10);
      const d = await getJSON(`https://superteam.fun/api/agents/listings/live?take=50&deadline=${day}`,
        { authorization: `Bearer ${env.SUPERTEAM_KEY}` });
      const list = Array.isArray(d) ? d : d.listings || d.data || [];
      return list.map((l) => ({
        src: "superteam", id: String(l.slug || ""), title: String(l.title || "").slice(0, 100),
        reward: l.rewardAmount ?? null, token: l.token ?? null,
        deadline: l.deadline ? String(l.deadline).slice(0, 10) : null,
        url: `https://superteam.fun/earn/listing/${l.slug || ""}`, agentAccess: l.agentAccess ?? null,
      }));
    }));
  }
  jobs.push(source("taskbounty", sources, items, async () => {
    const d = await getJSON("https://www.task-bounty.com/api/v1/tasks");
    return (d.data || []).map((t) => ({
      src: "taskbounty", id: "tb-" + String(t.id ?? ""), title: String(t.title || "").slice(0, 100),
      reward: t.bounty_cents != null ? t.bounty_cents / 100 : null, token: "USD", deadline: null,
      url: t.github_issue_url || null, language: t.language ?? null,
    }));
  }));
  await Promise.all(jobs);
  items.sort((a, b) => (a.src + a.id).localeCompare(b.src + b.id));
  return { generated_utc: now.toISOString(), sources, items };
}
