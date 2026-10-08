import { test, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import http from "node:http";
import { isUp, upState, REGIONS } from "../dist/esm/index.js";

// Every request stays on 127.0.0.1: both regions point at a closed local port unless a test says otherwise.
const REAL = { ...REGIONS }; const ENV = { NED_API: process.env.NED_API, NED_WATCH_API: process.env.NED_WATCH_API };
beforeEach(() => { REGIONS.us = "http://127.0.0.1:9"; REGIONS.eu = "http://127.0.0.1:9"; delete process.env.NED_API; delete process.env.NED_WATCH_API; });
afterEach(() => {
  Object.assign(REGIONS, REAL);
  for (const [k, v] of Object.entries(ENV)) { if (v === undefined) delete process.env[k]; else process.env[k] = v; }
});

const REPLIES = { "list.example": "[1, 2]", "null.example": "null", "string.example": '"up"', "garbage.example": "not json" };

function serve() {
  return new Promise((res) => {
    const srv = http.createServer((req, r) => {
      const host = req.url.split("/v1/up/")[1];
      r.setHeader("content-type", "application/json");
      r.end(REPLIES[host] ?? JSON.stringify({ host, state: host === "status.example" ? "degraded" : "unknown", watches: [], ask_again_s: 300 }));
    });
    srv.unref(); srv.listen(0, "127.0.0.1", () => res(`http://127.0.0.1:${srv.address().port}`));
  });
}

test("isUp by host and by URL", async () => {
  const base = await serve();
  assert.equal((await isUp("status.example", { base })).state, "degraded");
  assert.equal(await upState("https://status.example/api/v2/status.json?x=1", { base }), "degraded");
  assert.equal(await upState("HTTPS://Status.Example:8443/x#frag", { base }), "degraded");
  assert.equal(await upState("nobody.example", { base }), "unknown");
});

test("network failure is unknown, not a throw", async () => {
  const r = await isUp("api.openai.com", { base: "http://127.0.0.1:9", timeoutMs: 1000 });
  assert.equal(r.state, "unknown"); assert.ok(r.error);
  assert.equal((await isUp("", { base: "http://127.0.0.1:9" })).state, "unknown");
});

test("a host that isn't a hostname is unknown: bad host", async () => {
  for (const host of ["bad host.example", "user@status.example", "status_example", "exämple.com", "[::1]", "a".repeat(300), "../etc", "..", ".", "-x.example", "x.example-", "a..b"]) {
    const r = await isUp(host, { base: "http://127.0.0.1:9", timeoutMs: 1000 });
    assert.equal(r.state, "unknown", host); assert.equal(r.error, "bad host", host);
    assert.equal(await upState(host, { base: "http://127.0.0.1:9" }), "unknown");
  }
});

test("a non-string host never throws", async () => {
  for (const host of [null, undefined, 42, 1.5, ["status.example"], { h: 1 }, Symbol("x"), () => "status.example"]) {
    const r = await isUp(host, { base: "http://127.0.0.1:9", timeoutMs: 1000 });
    assert.equal(r.state, "unknown"); assert.ok(r.error === "bad host" || r.error === "host required", String(r.error));
    assert.equal(await upState(host), "unknown");
  }
});

test("odd options never throw", async () => {
  const base = await serve();
  assert.equal((await isUp("status.example", { base, ref: null })).state, "degraded");
  assert.equal((await isUp("status.example", { base, ref: 12345 })).state, "degraded");
  assert.equal((await isUp("status.example", { base, ref: "x\r\nInjected: 1" })).state, "degraded");   // control characters dropped
  assert.equal((await isUp("status.example", null)).state, "unknown");
  assert.equal((await isUp("status.example", "nonsense")).state, "unknown");
  assert.equal((await isUp("status.example", { base: 12345 })).state, "unknown");
  assert.equal((await isUp("status.example", { base, timeoutMs: "soon" })).state, "degraded");
  assert.equal(await upState("status.example", null), "unknown");
});

test("a base URL without a scheme is unknown, not a throw", async () => {
  assert.deepEqual(await isUp("status.example", { base: "127.0.0.1:9" }), { host: "status.example", state: "unknown", error: "TypeError" });
  assert.equal((await isUp("status.example", { base: "not a url" })).state, "unknown");
  assert.equal((await isUp("status.example", { base: "file:///etc" })).state, "unknown");
  // NED_API without a scheme: no throw, and the next station still answers
  process.env.NED_API = "127.0.0.1:9"; REGIONS.eu = "127.0.0.1:9";
  assert.deepEqual(await isUp("status.example"), { host: "status.example", state: "unknown", error: "TypeError" });
  REGIONS.eu = await serve();
  assert.equal(await upState("status.example"), "degraded");
});

test("a reply that isn't a JSON object is unknown", async () => {
  const base = await serve();
  for (const [host, error] of [["list.example", "bad reply"], ["null.example", "bad reply"], ["string.example", "bad reply"], ["garbage.example", "SyntaxError"]]) {
    assert.deepEqual(await isUp(host, { base }), { host, state: "unknown", error });
    assert.equal(await upState(host, { base }), "unknown");
  }
});
