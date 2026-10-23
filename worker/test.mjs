// Offline test: mocks fetch/caches and exercises routes + digest.
globalThis.caches = { default: { store: new Map(),
  async match(k) { const v = this.store.get(k.url); return v ? v.clone() : undefined; },
  async put(k, r) { this.store.set(k.url, r); } } };
globalThis.fetch = async (url, opts) => {
  if (String(url).includes("task-bounty")) return new Response(JSON.stringify({ data: [{ id: 7, title: "Fix bug", bounty_cents: 5000, github_issue_url: "https://github.com/x/y/issues/1", language: "py" }] }), { status: 200 });
  if (String(url).includes("superteam")) {
    if (!String(opts.headers.authorization).startsWith("Bearer ")) return new Response("no", { status: 401 });
    return new Response(JSON.stringify({ listings: [{ slug: "s1", title: "Bounty", rewardAmount: 100, token: "USDC", deadline: "2026-11-01T00:00:00Z" }] }), { status: 200 });
  }
  return new Response("x", { status: 404 });
};
const w = (await import("./worker.js")).default;
const kv = { m: new Map(), async get(k) { return this.m.get(k) ?? null; }, async put(k, v) { this.m.set(k, v); } };
const env = { FLEET_TOKEN: "t0k", SUPERTEAM_KEY: "sk", FLEET_KV: kv };
const ctx = { waitUntil: (p) => p };
const assert = (c, m) => { if (!c) { console.error("FAIL", m); process.exit(1); } };
let r = await w.fetch(new Request("https://w/health"), env, ctx); assert(r.status === 200, "health");
r = await w.fetch(new Request("https://w/watch"), env, ctx); assert(r.status === 401, "401");
r = await w.fetch(new Request("https://w/watch", { headers: { authorization: "Bearer bad" } }), env, ctx); assert(r.status === 401, "bad");
r = await w.fetch(new Request("https://w/watch?fresh=1", { headers: { authorization: "Bearer t0k" } }), env, ctx);
let d = await r.json(); assert(d.items.length === 2 && d.sources.superteam.ok && d.sources.taskbounty.ok, "digest");
assert(d.new.length === 2, "new first"); assert(!JSON.stringify(d).includes("sk\""), "no secret");
r = await w.fetch(new Request("https://w/watch?fresh=1", { headers: { authorization: "Bearer t0k" } }), env, ctx);
d = await r.json(); assert(d.new.length === 0, "new second");
await w.scheduled({}, env, ctx); assert(kv.m.has("watch:last"), "kv last");
r = await w.fetch(new Request("https://w/nope"), env, ctx); assert(r.status === 404, "404");
console.log("worker tests OK");
