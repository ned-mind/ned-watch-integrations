import { after, before, test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { Ned, NedConfigError, NedError, seconds, slug, fingerprint, verifySignature } from "../dist/esm/index.js";
import { age, entry, events, hooks, startNed, tmpState, waitFor } from "./helpers.mjs";

let srv, base, hook;
before(async () => { srv = await startNed(); base = srv.base; hook = `${base}/_test/hook`; });
after(async () => srv.stop());
const mk = (o = {}) => new Ned({ base, callbackUrl: hook, state: tmpState(), logger: () => {}, ...o });

test("durations and names", () => {
  assert.equal(seconds("90s"), 90); assert.equal(seconds("1h30m"), 5400); assert.equal(seconds(300), 300);
  assert.throws(() => seconds("soon"));
  assert.equal(slug("nightly sync/eu"), "nightly-sync-eu");
});

test("fingerprint matches the Python client byte for byte (shared state file)", () => {
  // python: nedwatch._util.fingerprint({"type":"deadman","callback_url":"https://x.example/h","interval_s":3600,"condition":{"label":"nightly-sync"}})
  assert.equal(fingerprint({ type: "deadman", callback_url: "https://x.example/h", interval_s: 3600, condition: { label: "nightly-sync" }, meta: { ref: "js" } }),
               "68149b4127070eaf");
  assert.equal(fingerprint({ type: "deadman", callback_url: "https://x.example/h", interval_s: 3600, condition: { label: "nightly-sync", arm: true } }),
               "f2c8233e8444cd44");                                                            // the v1.9 deadman body (arm is in it)
});

test("deadman: registers once, tags entry js, verifies signed test callback", async () => {
  const state = tmpState();
  const ned = mk({ state });
  const w = ned.deadman("nightly-sync", { every: "1h" });
  const rec = await w.ensure();
  assert.match(rec.id, /^w_[0-9a-f]{12}$/);
  assert.equal(await entry(base, rec.id), "js");
  assert.equal((await new Ned({ base, callbackUrl: hook, state }).deadman("nightly-sync", { every: "1h" }).ensure()).id, rec.id);
  const key = JSON.parse(readFileSync(state, "utf8"))[base].agent_key;
  assert.equal((await new Ned({ agentKey: key, base, callbackUrl: hook, state: false }).deadman("nightly-sync", { every: "1h" }).ensure()).id, rec.id);
  const h = (await hooks(base)).find((x) => x.body.watch_id === rec.id && x.body.event === "test");
  assert.ok(verifySignature(rec.secret, h.headers, h.raw));
  assert.ok(!verifySignature("whs_wrong", h.headers, h.raw));
  assert.ok(!JSON.stringify(w).includes(rec.secret));                     // never serialises the secret
});

test("explicit ref", async () => {
  const r = await mk({ ref: "Cron" }).deadman("ref-test").ensure();
  assert.equal(await entry(base, r.id), "cron");
});

test("wrap: arms first, checks in on success only, then fire and clear", async () => {
  const ned = mk();
  const dm = ned.deadman("wrapped", { every: "5m" });
  const ok = dm.wrap(async (x) => x * 2);
  const boom = dm.wrap(() => { throw new Error("nope"); });
  await assert.rejects(boom(), /nope/);                                 // first run fails: still armed
  const id = dm.id;
  const armed = (await ned.get(id)).last_checkin;
  assert.ok(armed);
  await assert.rejects(boom(), /nope/);
  assert.equal((await ned.get(id)).last_checkin, armed);
  await age(base, id, 3600);
  assert.ok(await waitFor(async () => (await events(base, id)).includes("fire")));
  assert.equal(await ok(21), 42);
  assert.ok(await waitFor(async () => (await events(base, id)).includes("clear")));
});

test("run: start/finish; failure semantics", async () => {
  const ned = mk();
  assert.equal(await ned.run("etl", { max: "20m" }, async () => "done"), "done");
  const ow = ned.state.watch(base, "overrun:etl");
  assert.equal((await ned.get(ow.id)).run.last.status, "finished");
  await assert.rejects(ned.run("etl", { max: "20m" }, () => {
    throw new TypeError("bad config at https://u:hunter2@db.example/x?api_key=abc123def\nmore");
  }));
  const last = (await ned.get(ow.id)).run.last;                                      // v1.9: reported as failed at once
  assert.equal(last.status, "failed");
  assert.equal(last.error, "TypeError: bad config at https://[redacted]@db.example/x?api_key=[redacted]");
  assert.ok(await waitFor(async () => (await hooks(base)).some((h) => h.body.watch_id === ow.id && h.body.event === "fire"
    && h.body.reason.includes("reported failure: TypeError"))));
  await ned.run("etl", { max: "20m" }, () => 1);                                    // the next good run clears it
  assert.ok(await waitFor(async () => (await events(base, ow.id)).includes("clear")));
  await assert.rejects(ned.run("kept", { max: "20m", onError: "leave_open" }, () => { throw new Error("x"); }));
  assert.ok((await ned.get(ned.state.watch(base, "overrun:kept").id)).run.open);
  await assert.rejects(ned.run("both", { max: "20m", every: "1d" }, () => { throw new Error("crash"); }));
  const o2 = ned.state.watch(base, "overrun:both"), d2 = ned.state.watch(base, "deadman:both");
  assert.equal((await ned.get(o2.id)).run.last.status, "failed");
  const armed = (await ned.get(d2.id)).last_checkin;
  await ned.run("both", { max: "20m", every: "1d" }, () => 1);
  assert.notEqual((await ned.get(d2.id)).last_checkin, armed);                      // success checks in
});

test("checkin by name, id, and secret; spec change retires old watch; 404 re-registers", async () => {
  const ned = mk();
  const w = ned.deadman("by-name", { every: "1h" });
  const r = await w.ensure();
  assert.equal((await ned.checkin("by-name")).ok, true);
  assert.equal((await ned.checkin(r.id)).ok, true);
  await assert.rejects(new Ned({ base, state: false }).checkin(r.id), NedConfigError);
  assert.equal((await new Ned({ base, state: false }).checkin(r.id, r.secret)).ok, true);
  await assert.rejects(ned.checkin(r.id, "whs_no"), (e) => e instanceof NedError && e.status === 401);
  const b = await ned.deadman("by-name", { every: "2h" }).ensure();
  assert.notEqual(b.id, r.id);
  assert.equal((await ned.get(r.id)).status, "cancelled");
  const g = ned.deadman("gone", { every: "1h" });
  const old = (await g.ensure()).id;
  await ned.call("DELETE", `/v1/watches/${old}`, { bearer: JSON.parse(readFileSync(ned.state.path, "utf8"))[base].agent_key });
  await g.checkin();
  assert.notEqual(g.id, old);
});

test("fail-open, strict, missing callback", async () => {
  const dead = new Ned({ base: "http://127.0.0.1:9", callbackUrl: "http://127.0.0.1:9/h", state: tmpState(), retries: 0, timeoutMs: 1000, logger: () => {} });
  assert.equal(await dead.deadman("x").wrap(() => "done")(), "done");
  assert.equal(await dead.run("y", { max: "5m" }, () => "ran"), "ran");
  const strict = new Ned({ base: "http://127.0.0.1:9", callbackUrl: "http://127.0.0.1:9/h", state: false, retries: 0, timeoutMs: 1000, strict: true });
  await assert.rejects(strict.deadman("x").wrap(() => 1)(), NedError);
  await assert.rejects(new Ned({ base, state: false }).deadman("x").ensure(), NedConfigError);
});

test("CommonJS build works with require()", async () => {
  const require = createRequire(import.meta.url);
  const cjs = require("../dist/cjs/index.js");
  assert.equal(typeof cjs.Ned, "function");
  const r = await new cjs.Ned({ base, callbackUrl: hook, state: tmpState() }).deadman("from-cjs").ensure();
  assert.equal(await entry(base, r.id), "js");
});

test("stateless container does not re-arm", async () => {
  const st = tmpState();
  await mk({ state: st }).deadman("container-job").ensure();
  const key = JSON.parse(readFileSync(st, "utf8"))[base].agent_key;
  const once = async () => {
    const ned = new Ned({ agentKey: key, base, callbackUrl: hook, state: false, logger: () => {} });
    const dm = ned.deadman("container-job");
    await assert.rejects(dm.wrap(() => { throw new Error("always fails"); })());
    return [ned, dm.id];
  };
  const [ned, id] = await once();
  const armed = (await ned.get(id)).last_checkin;
  assert.ok(armed);
  await once(); await once();
  assert.equal((await ned.get(id)).last_checkin, armed);
});

test("detects the framework from package.json and tags with it", async () => {
  const { mkdtempSync, writeFileSync } = await import("node:fs");
  const { tmpdir } = await import("node:os");
  const { join } = await import("node:path");
  const { detectFramework, defaultName } = await import("../dist/esm/index.js");
  const dir = mkdtempSync(join(tmpdir(), "nedproj-"));
  writeFileSync(join(dir, "package.json"), JSON.stringify({ name: "@acme/support-bot", dependencies: { "@openai/agents": "^0.1.0" } }));
  assert.equal(detectFramework(dir), "openai-agents");
  const cwd = process.cwd();
  process.chdir(dir);
  try {
    const ned = mk();
    assert.equal(ned.ref, "openai-agents");
    const r = await ned.deadman("detected").ensure();
    assert.equal(await entry(base, r.id), "openai-agents");
    const argv1 = process.argv[1]; process.argv[1] = "/x/index.js";
    try { assert.equal(defaultName(), "support-bot"); } finally { process.argv[1] = argv1; }
  } finally { process.chdir(cwd); }
});

test("deadman is armed at registration (condition.arm) and stays idempotent", async () => {
  const st = tmpState();
  const ned = mk({ state: st });
  const r = await ned.deadman("armed-at-birth", { every: "5m" }).ensure();
  const g = await ned.get(r.id);
  assert.ok(g.last_checkin);
  assert.deepEqual(g.condition, { label: "armed-at-birth", arm: true });
  const key = JSON.parse(readFileSync(st, "utf8"))[base].agent_key;
  assert.equal((await new Ned({ agentKey: key, base, callbackUrl: hook, state: false }).deadman("armed-at-birth", { every: "5m" }).ensure()).id, r.id);
});

test("falls back to a client-side arm when the server refuses condition.arm", async () => {
  const ned = mk();
  const real = ned.call.bind(ned);
  ned.call = async (method, path, o = {}) => {
    if (path === "/v1/watches" && o.body?.condition?.arm) throw new NedError("422", 422, { error: "unknown condition key arm" });
    return real(method, path, o);
  };
  const dm = ned.deadman("old-server");
  await assert.rejects(dm.wrap(() => { throw new Error("fails"); })());
  const g = await ned.get(dm.id);
  assert.deepEqual(g.condition, { label: "old-server" });
  assert.ok(g.last_checkin);
});

test("errorSummary redacts and truncates", async () => {
  const { errorSummary } = await import("../dist/esm/index.js");
  const out = errorSummary(new Error("Authorization: Bearer nw_" + "a".repeat(48)));
  assert.ok(out.startsWith("Error: Authorization: Bearer") && !out.includes("a".repeat(20)));
  assert.ok(errorSummary("x".repeat(500)).length <= 200);
});
