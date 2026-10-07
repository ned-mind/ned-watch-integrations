import { test } from "node:test";
import assert from "node:assert/strict";
import http from "node:http";
import { isUp, upState } from "../dist/esm/index.js";

function serve() {
  return new Promise((res) => {
    const srv = http.createServer((req, r) => {
      const host = req.url.split("/v1/up/")[1];
      r.setHeader("content-type", "application/json");
      r.end(JSON.stringify({ host, state: host === "status.example" ? "degraded" : "unknown", watches: [], ask_again_s: 300 }));
    });
    srv.unref(); srv.listen(0, "127.0.0.1", () => res(`http://127.0.0.1:${srv.address().port}`));
  });
}

test("isUp by host and by URL", async () => {
  const base = await serve();
  assert.equal((await isUp("status.example", { base })).state, "degraded");
  assert.equal(await upState("https://status.example/api/v2/status.json?x=1", { base }), "degraded");
  assert.equal(await upState("nobody.example", { base }), "unknown");
});

test("network failure is unknown, not a throw", async () => {
  const r = await isUp("api.openai.com", { base: "http://127.0.0.1:9", timeoutMs: 1000 });
  assert.equal(r.state, "unknown"); assert.ok(r.error);
  assert.equal((await isUp("", { base: "http://127.0.0.1:9" })).state, "unknown");
});
