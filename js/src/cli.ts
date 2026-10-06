#!/usr/bin/env node
// nedwatch: command line for Ned Watch (Node). Same commands, flags and state file as the Python CLI.
//   nedwatch setup --callback URL --name nightly-sync --every 1h [--max 30m]
//   nedwatch checkin nightly-sync
//   nedwatch run --name backup --max 30m [--every 1d] -- ./backup.sh      (also: ned-run ...)
//   nedwatch doctor [--create]
//   nedwatch status [name]
// Secrets stay in the state file (mode 0600) and are printed only with --show-secrets.
import { spawn } from "node:child_process";
import { basename } from "node:path";
import { parseArgs } from "node:util";
import { Ned, NedConfigError, NedError, VERSION } from "./client.js";

const COMMON = {
  base: { type: "string" }, region: { type: "string" }, state: { type: "string" }, ref: { type: "string" },
  callback: { type: "string" }, name: { type: "string" }, every: { type: "string" }, max: { type: "string" },
  create: { type: "boolean" }, "show-secrets": { type: "boolean" }, quiet: { type: "boolean", short: "q" },
  "never-fail": { type: "boolean" }, "on-error": { type: "string" }, help: { type: "boolean", short: "h" },
  version: { type: "boolean" },
} as const;

type Opts = { [K in keyof typeof COMMON]?: (typeof COMMON)[K]["type"] extends "boolean" ? boolean : string };

function mkNed(o: Opts, ref?: string): Ned {
  return new Ned({ base: o.base, region: o.region as "us" | "eu" | undefined, state: o.state, callbackUrl: o.callback,
                   ref: ref || o.ref || process.env.NED_REF || "cli" });
}

const ok = (m: string) => console.log(`  ok    ${m}`);
const bad = (m: string) => console.log(`  FAIL  ${m}`);

async function doctor(o: Opts): Promise<number> {
  const ned = mkNed(o);
  console.log(`Ned Watch doctor (ned-watch ${VERSION}, node ${process.version})`);
  console.log(`  api       ${ned.base}`);
  console.log(`  ref       ${ned.ref}`);
  console.log(`  key       ${ned.hasKey ? "set" : "not set (your first registration creates one)"}`);
  console.log(`  callback  ${ned.callbackUrl || "not set (--callback or NED_CALLBACK_URL)"}`);
  console.log(`  state     ${ned.state.path || "memory only"}`);
  let fails = 0;
  const t0 = Date.now();
  try {
    const h = await ned.health();
    ok(`reached Ned in ${Date.now() - t0} ms (node ${h.node}, db ${h.db ? "up" : "DOWN"})`);
  } catch (e: any) {
    bad(`can't reach ${ned.base}: ${e.message}`);
    return 1;
  }
  if (ned.hasKey) {
    try {
      const b = await ned.balance();
      ok(`agent key accepted (${b.agent_id}; ${b.free_used}/${b.free_watches} free watches used, balance ${b.balance_cents}c)`);
    } catch (e: any) { fails++; bad(`agent key rejected: ${e.message}`); }
  }
  if (!ned.callbackUrl) console.log("  skip  callback test: no callback URL");
  else if (!ned.hasKey && !o.create) console.log("  skip  callback test: no agent key yet; run again with --create to make your agent and test the callback");
  else {
    try {
      const res = await ned.register("deadman", { interval_s: 3600, condition: { label: `doctor-${Math.random().toString(16).slice(2, 10)}` } });
      const tc = res.test_callback || {};
      if (tc.delivered) ok(`test callback delivered to your URL (HTTP ${tc.status})`);
      else { fails++; bad(`test callback not delivered: ${tc.problem || tc.status}`); }
      await ned.cancel(res.watch_id).catch(() => undefined);
    } catch (e: any) { fails++; bad(`couldn't register the test watch: ${e.message}`); }
  }
  if (ned.hasKey) {
    for (const [slot, rec] of Object.entries(ned.state.watches(ned.base)).sort()) {
      try {
        const w = await ned.get(rec.id);
        ok(`${slot.padEnd(32)} ${rec.id}  ${w.fired ? "FIRED" : w.status}  last check-in ${w.last_checkin || "-"}`);
      } catch (e: any) { bad(`${slot}: ${e.message}`); }
    }
  }
  console.log(fails ? `${fails} problem(s)` : "all good");
  return fails ? 1 : 0;
}

async function setup(o: Opts): Promise<number> {
  const ned = mkNed(o);
  const name = o.name || process.env.NED_WATCH_NAME || basename(process.cwd()) || "agent";
  try {
    if (o.max) {
      const w = ned.overrun(name, { max: o.max });
      const r = await w.ensure();
      console.log(`overrun watch '${w.name}': ${r.id} (fires if a run is still open after ${o.max})`);
      console.log(`wrap your job:  ned-run --name ${w.name} --max ${o.max} -- <command>`);
    }
    const every = o.every || "1h";
    const d = ned.deadman(name, { every });
    const r = await d.ensure();
    await d.checkin();
    console.log(`deadman watch '${d.name}': ${r.id} (fires if no check-in for ${every}); first check-in done`);
    console.log(`after each successful run:  nedwatch checkin ${d.name}`);
    console.log(`saved to ${ned.state.path || "memory"} (agent key and signing secrets; mode 0600)`);
    if (o["show-secrets"]) {
      console.log(`NED_AGENT_KEY=${(ned as any).key}`);
      console.log(`NED_WATCH_ID=${r.id}`);
      console.log(`NED_SIGNING_SECRET=${r.secret}`);
    }
    return 0;
  } catch (e: any) {
    console.error(`error: ${e.message}`);
    return e instanceof NedConfigError ? 2 : 1;
  }
}

async function checkin(o: Opts, watch?: string): Promise<number> {
  if (!watch) { console.error("usage: nedwatch checkin <name | w_id>"); return 2; }
  const ned = mkNed(o);
  try {
    const r = await ned.checkin(watch, watch.startsWith("w_") ? process.env.NED_SIGNING_SECRET : undefined);
    if (!o.quiet) console.log(`checked in: ${r.watch_id} (next deadline in ${r.next_deadline_s} s)`);
    return 0;
  } catch (e: any) {
    console.error(`nedwatch: check-in failed: ${e.message}`);
    return o["never-fail"] ? 0 : 1;
  }
}

async function status(o: Opts, name?: string): Promise<number> {
  const ned = mkNed(o);
  const recs = Object.entries(ned.state.watches(ned.base)).filter(([slot]) => !name || slot.split(":")[1] === name);
  if (!recs.length) { console.log("no watches in the state file"); return 1; }
  for (const [slot, rec] of recs.sort()) {
    try {
      const w = await ned.get(rec.id);
      console.log(`${slot.padEnd(32)} ${rec.id}  ${w.fired ? "FIRED" : w.status}  last check-in ${w.last_checkin || "-"}`);
    } catch (e: any) { console.log(`${slot.padEnd(32)} ${rec.id}  error: ${e.message}`); }
  }
  return 0;
}

export async function runCommand(o: Opts, cmd: string[]): Promise<number> {
  if (!cmd.length) { console.error("usage: ned-run [--name N] [--max 1h] [--every 1d] -- <command> [args...]"); return 2; }
  const name = o.name || process.env.NED_WATCH_NAME || basename(cmd[0]) || "job";
  const ned = mkNed(o, o.ref || process.env.NED_REF || "cron");
  const onError = (o["on-error"] || "report") as "report" | "auto" | "leave_open" | "finish";
  let code = 0;
  try {
    await ned.run(name, { max: o.max || "1h", every: o.every, onError }, () => new Promise<void>((resolve, reject) => {
      const child = spawn(cmd[0], cmd.slice(1), { stdio: "inherit" });
      const fwd = (sig: NodeJS.Signals) => { try { child.kill(sig); } catch { /* gone */ } };
      const sigs: NodeJS.Signals[] = ["SIGINT", "SIGTERM", "SIGHUP"];
      sigs.forEach((s) => process.on(s, fwd));
      const fail = (msg: string) => Object.assign(new Error(msg), { nedError: msg });   // only this reaches Ned, never the command line
      child.on("error", (e) => { console.error(`ned-run: can't start ${cmd[0]}: ${e.message}`); code = 127; reject(fail(`could not start the command (${(e as any).code || e.name})`)); });
      child.on("exit", (c, sig) => {
        sigs.forEach((s) => process.off(s, fwd));
        code = c ?? (sig ? 128 + (({ SIGINT: 2, SIGTERM: 15, SIGHUP: 1, SIGKILL: 9 } as Record<string, number>)[sig] || 1) : 1);
        if (code === 0) resolve(); else reject(fail(sig ? `killed by signal ${sig}` : `exit code ${code}`));
      });
    }));
  } catch (e) {
    if (e instanceof NedError) { console.error(`ned-run: ${e.message}`); return code || 1; }   // only when strict
  }
  return code;
}

const HELP = `nedwatch ${VERSION}: know when your agent silently stops.
  nedwatch setup   --callback URL [--name N] [--every 1h] [--max 30m] [--show-secrets]
  nedwatch checkin <name | w_id> [-q] [--never-fail]
  nedwatch run     [--name N] [--max 1h] [--every 1d] [--on-error report|leave_open|finish] -- <command...>
  nedwatch doctor  [--callback URL] [--create]
  nedwatch status  [name]
common: --base URL  --region us|eu  --state FILE  --ref TAG`;

export async function main(argv = process.argv.slice(2)): Promise<number> {
  const { values: o, positionals } = parseArgs({ args: argv, options: COMMON, allowPositionals: true, strict: true });
  if (o.version) { console.log(`nedwatch ${VERSION}`); return 0; }
  const [cmd, ...rest] = positionals;
  if (o.help || !cmd) { console.log(HELP); return cmd ? 0 : 2; }
  switch (cmd) {
    case "doctor": return doctor(o);
    case "setup": return setup(o);
    case "checkin": return checkin(o, rest[0]);
    case "status": return status(o, rest[0]);
    case "run": return runCommand(o, rest);
    default: console.error(`unknown command ${cmd}\n${HELP}`); return 2;
  }
}

if (require_main()) main().then((c) => process.exit(c), (e) => { console.error(e?.message || e); process.exit(2); });

function require_main(): boolean {
  const a = process.argv[1] || "";
  return /(^|[\\/])(nedwatch|ned-watch|cli\.js)$/.test(a);
}
