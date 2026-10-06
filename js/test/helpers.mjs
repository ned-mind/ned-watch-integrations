// Starts the local Ned Watch (../../testserver/run.py, on the repo's .venv) for a test file.
import { spawn } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { createInterface } from "node:readline";

const here = dirname(fileURLToPath(import.meta.url));
export const ROOT = join(here, "..", "..");
const PY = process.env.NED_TEST_SERVER_PYTHON || join(ROOT, ".venv", "bin", "python");

for (const k of ["NED_AGENT_KEY", "NED_API", "NED_WATCH_API", "NED_CALLBACK_URL", "NED_REF", "NED_STATE", "NED_REGION",
                 "NED_SIGNING_SECRET", "NED_WATCH_ID", "NED_WATCH_NAME"]) delete process.env[k];

export async function startNed() {
  if (process.env.NED_TEST_BASE) return { base: process.env.NED_TEST_BASE, stop: async () => {} };
  const env = Object.fromEntries(Object.entries(process.env).filter(([k]) => !k.toLowerCase().endsWith("_proxy")));
  const p = spawn(PY, [join(ROOT, "testserver", "run.py")], { env, stdio: ["ignore", "pipe", "pipe"] });
  const rl = createInterface({ input: p.stdout });
  const base = await new Promise((resolve, reject) => {
    const t = setTimeout(() => reject(new Error("local Ned Watch didn't start")), 30000);
    rl.on("line", (l) => { if (l.startsWith("READY ")) { clearTimeout(t); resolve(l.split(" ")[1]); } });
    p.on("exit", (c) => reject(new Error(`server exited ${c}`)));
  });
  p.stderr.resume();
  return { base, stop: async () => { p.kill("SIGTERM"); } };
}

export const tmpState = () => join(mkdtempSync(join(tmpdir(), "nedjs-")), "state.json");
const j = async (r) => { const t = await r.text(); return t ? JSON.parse(t) : null; };
export const hooks = async (base) => j(await fetch(`${base}/_test/hooks`));
export const entry = async (base, wid) => (await j(await fetch(`${base}/_test/entry/${wid}`))).entry;
export const age = async (base, wid, s = 3600) => j(await fetch(`${base}/_test/age/${wid}?s=${s}`, { method: "POST" }));
export const events = async (base, wid) => (await hooks(base)).filter((h) => h.body.watch_id === wid).map((h) => h.body.event);
export async function waitFor(pred, timeoutMs = 10000) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) { const v = await pred(); if (v) return v; await new Promise((r) => setTimeout(r, 100)); }
  return null;
}
