#!/usr/bin/env node
// ned-run [--name N] [--max 1h] [--every 1d] -- <command...>
// Starts an overrun run, runs the command, finishes the run; with --every also checks in to a deadman on exit 0.
// Exits with the command's exit code. Ned being unreachable never stops the command.
import { parseArgs } from "node:util";
import { runCommand } from "./cli.js";

const { values, positionals } = parseArgs({
  args: process.argv.slice(2), allowPositionals: true, strict: true,
  options: { base: { type: "string" }, region: { type: "string" }, state: { type: "string" }, ref: { type: "string" },
             callback: { type: "string" }, name: { type: "string" }, every: { type: "string" }, max: { type: "string" },
             "on-error": { type: "string" } },
});
runCommand(values, positionals).then((c) => process.exit(c), (e) => { console.error(e?.message || e); process.exit(2); });
