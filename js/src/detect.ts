// Which agent framework does this project use? Read from the nearest package.json's dependencies (it never imports
// anything). Used to tag new agents (X-Ned-Ref) and to pick a default watch name.
import { existsSync, readFileSync } from "node:fs";
import { basename, dirname, join, resolve } from "node:path";

const FRAMEWORKS: [string, string][] = [
  ["@langchain/langgraph", "langgraph"],
  ["@openai/agents", "openai-agents"],
  ["@anthropic-ai/claude-agent-sdk", "claude-agent-sdk"],
  ["@mastra/core", "mastra"],
  ["@langchain/core", "langchain"],
  ["langchain", "langchain"],
  ["llamaindex", "llamaindex"],
  ["ai", "vercel-ai"],
];

function nearestPackage(start = process.cwd()): Record<string, any> | null {
  let dir = resolve(start);
  for (let i = 0; i < 20; i++) {
    const p = join(dir, "package.json");
    if (existsSync(p)) {
      try { return JSON.parse(readFileSync(p, "utf8")); } catch { return null; }
    }
    const up = dirname(dir);
    if (up === dir) break;
    dir = up;
  }
  return null;
}

export function detectFramework(cwd?: string): string | null {
  const pkg = nearestPackage(cwd);
  if (!pkg) return null;
  const deps = { ...(pkg.dependencies || {}), ...(pkg.devDependencies || {}) };
  for (const [mod, ref] of FRAMEWORKS) if (mod in deps) return ref;
  return null;
}

/** $NED_WATCH_NAME, else the running script's name (nightly-sync.mjs -> nightly-sync), else package name, else "agent". */
export function defaultName(): string {
  if (process.env.NED_WATCH_NAME) return process.env.NED_WATCH_NAME;
  const script = process.argv[1] ? basename(process.argv[1]).replace(/\.(c|m)?(j|t)s$/, "") : "";
  if (script && !["node", "index", "main", "cli", "test"].includes(script)) return script;
  const pkg = nearestPackage();
  if (pkg?.name) return String(pkg.name).replace(/^@[^/]+\//, "");
  return script || "agent";
}
