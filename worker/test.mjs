// Offline test: node worker/test.mjs (mocks fetch + KV)
import assert from "node:assert/strict";
const W = await import(new URL("./worker.js", import.meta.url));
const calls = [];
globalThis.fetch = async (url, opts) => {
  calls.push([url, opts.headers]);
  if (String(url).includes("superteam")) {
    if (opts.headers.authorization !== "Bearer st-secret") return new Response("no", { status: 401 });
    return Response.json({ listings: [{ slug: "build-x", title: "Build X", rewardAmount: 500, token: "USDC", deadline: "2026-11-01T00:00:00Z", agentAccess: "AGENT_ALLOWED" }] });
  }
  if (String(url).includes("task-bounty")) return Response.json({ data: [{ id: 7, title: "Fix bug", bounty_cents: 2500, github_issue_url: "https://github.com/o/r/issues/1" }] });
  return new Response("?", { status: 404 });
};
const store = new Map();
const KV = { get: async (k) => store.get(k) ?? null, put: async (k, v) => void store.set(k, v) };
const env = { FLEET_TOKEN: "tok", SUPERTEAM_KEY: "st-secret", FLEET_KV: KV };
const req = (path, token) => new Request("https://w.example" + path, token ? { headers: { authorization: "Bearer " + token } } : {});

let r = await W.default.fetch(req("/health"), env); assert.equal(r.status, 200);
r = await W.default.fetch(req("/watch"), env); assert.equal(r.status, 401);
r = await W.default.fetch(req("/watch", "nope"), env); assert.equal(r.status, 401);
r = await W.default.fetch(req("/nope", "tok"), env); assert.equal(r.status, 404);
r = await W.default.fetch(req("/watch", "tok"), env); assert.equal(r.status, 200);
let d = await r.json();
assert.deepEqual(d.items.map((i) => i.id), ["superteam:build-x", "taskbounty:7"]);
assert.deepEqual(d.new, ["superteam:build-x", "taskbounty:7"]);
assert.equal(d.items[1].reward, 25);
assert.ok(!JSON.stringify(d).includes("st-secret"), "secret leaked");
const n = calls.length;
r = await W.default.fetch(req("/watch", "tok"), env); d = await r.json();
assert.equal(d.cached, true); assert.equal(calls.length, n, "cache should avoid upstream calls");
r = await W.default.fetch(req("/watch?fresh=1", "tok"), env); d = await r.json();
assert.deepEqual(d.new, []);
// upstream failure isolated
const bad = await W.buildDigest({ SUPERTEAM_KEY: "wrong" });
assert.equal(bad.sources.superteam.ok, false); assert.equal(bad.sources.taskbounty.ok, true);
// scheduled
let waited; await W.default.scheduled({}, env, { waitUntil: (p) => (waited = p) }); await waited;
console.log("worker tests ok");
