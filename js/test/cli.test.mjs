import { after, before, test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { createServer } from "node:net";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { Ned } from "../dist/esm/index.js";
import { entry, startNed, tmpState } from "./helpers.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const CLI = join(here, "..", "dist", "esm", "cli.js");
const RUN = join(here, "..", "dist", "esm", "ned-run.js");
let srv, base, hook;
before(async () => { srv = await startNed(); base = srv.base; hook = `${base}/_test/hook`; });
after(async () => srv.stop());

const sh = (bin, args, state, env = {}) => spawnSync(process.execPath, [bin, ...args], {
  encoding: "utf8", timeout: 120000, env: { ...process.env, NED_API: base, NED_CALLBACK_URL: hook, NED_STATE: state, ...env } });
const secretsIn = (state) => { const d = JSON.parse(readFileSync(state, "utf8"))[base] || {};
  return [d.agent_key, ...Object.values(d.watches || {}).map((w) => w.secret)]; };

test("setup + checkin never print secrets", () => {
  const st = tmpState();
  const p = sh(CLI, ["setup", "--name", "cli-job", "--every", "1h", "--max", "30m"], st);
  assert.equal(p.status, 0, p.stderr);
  for (const s of secretsIn(st)) assert.ok(s && !(p.stdout + p.stderr).includes(s));
  const c = sh(CLI, ["checkin", "cli-job"], st);
  assert.equal(c.status, 0, c.stderr);
  assert.match(c.stdout, /checked in/);
});

test("doctor", async () => {
  const st = tmpState();
  let p = sh(CLI, ["doctor"], st);
  assert.equal(p.status, 0); assert.match(p.stdout, /reached Ned/); assert.match(p.stdout, /--create/);
  p = sh(CLI, ["doctor", "--create"], st);
  assert.equal(p.status, 0, p.stdout); assert.match(p.stdout, /test callback delivered/);
  p = sh(CLI, ["doctor"], st);
  assert.match(p.stdout, /agent key accepted/);
  for (const s of secretsIn(st)) assert.ok(!p.stdout.includes(s));
  const port = await new Promise((r) => { const s = createServer().listen(0, "127.0.0.1", () => { const x = s.address().port; s.close(() => r(x)); }); });
  p = sh(CLI, ["doctor"], st, { NED_CALLBACK_URL: `http://127.0.0.1:${port}/nothing` });
  assert.equal(p.status, 1); assert.match(p.stdout, /not delivered/);
  p = sh(CLI, ["doctor", "--base", "http://127.0.0.1:9"], st);
  assert.equal(p.status, 1); assert.match(p.stdout, /can't reach/);
});

test("ned-run: exit codes, overrun + deadman, tag cron", async () => {
  const st = tmpState();
  let p = sh(RUN, ["--name", "backup", "--max", "30m", "--every", "1d", "--", "sh", "-c", "echo hi"], st);
  assert.equal(p.status, 0, p.stderr); assert.match(p.stdout, /hi/);
  const ws = JSON.parse(readFileSync(st, "utf8"))[base].watches;
  const ned = new Ned({ base, state: st });
  assert.equal((await ned.get(ws["overrun:backup"].id)).run.last.status, "finished");
  const first = (await ned.get(ws["deadman:backup"].id)).last_checkin;
  assert.ok(first);
  assert.equal(await entry(base, ws["overrun:backup"].id), "cron");
  p = sh(RUN, ["--name", "backup", "--max", "30m", "--every", "1d", "--", "sh", "-c", "exit 3"], st);
  assert.equal(p.status, 3);
  assert.equal((await ned.get(ws["deadman:backup"].id)).last_checkin, first);
  let last = (await ned.get(ws["overrun:backup"].id)).run.last;
  assert.equal(last.status, "failed"); assert.equal(last.error, "exit code 3");
  p = sh(RUN, ["--max", "30m", "--", "sh", "-c", "exit 1 # password=hunter2"], st);
  assert.equal(p.status, 1);
  const o2 = JSON.parse(readFileSync(st, "utf8"))[base].watches["overrun:sh"];
  last = (await ned.get(o2.id)).run.last;
  assert.equal(last.status, "failed"); assert.equal(last.error, "exit code 1");   // never the command line
  p = sh(RUN, ["--", "/no/such/cmd"], st);
  assert.equal(p.status, 127);
  p = sh(CLI, ["run", "--name", "via-nedwatch", "--", "true"], st);
  assert.equal(p.status, 0, p.stderr);
});

test("ned-run with Ned down still runs the command", () => {
  const st = tmpState();
  const p = sh(RUN, ["--name", "offline", "--", "sh", "-c", "echo ran"], st, { NED_API: "http://127.0.0.1:9" });
  assert.equal(p.status, 0); assert.match(p.stdout, /ran/); assert.match(p.stderr, /unaffected/);
});

test("python and node share the state file", () => {
  const st = tmpState();
  assert.equal(sh(CLI, ["setup", "--name", "shared-job", "--every", "1h"], st).status, 0);
  const py = join(here, "..", "..", ".venv", "bin", "nedwatch");
  const p = spawnSync(py, ["checkin", "shared-job"], { encoding: "utf8", env: { ...process.env, NED_API: base, NED_STATE: st } });
  assert.equal(p.status, 0, p.stderr);
  assert.match(p.stdout, /checked in/);
});
