// Build without npm: tsc from ../.tools (TypeScript 5.9.3, fetched by tarball through the egress proxy).
// dist/esm (ESM), dist/cjs (CommonJS, marked by its own package.json), dist/types (.d.ts).
import { execFileSync } from "node:child_process";
import { chmodSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
import { existsSync } from "node:fs";
const local = join(here, "node_modules", "typescript", "bin", "tsc");
const tsc = process.env.TSC || (existsSync(local) ? local : join(here, "..", ".tools", "typescript", "bin", "tsc"));
const run = (...args) => execFileSync(process.execPath, [tsc, "-p", join(here, "tsconfig.json"), ...args], { stdio: "inherit" });

rmSync(join(here, "dist"), { recursive: true, force: true });
run("--outDir", join(here, "dist/esm"));
run("--outDir", join(here, "dist/cjs"), "--module", "CommonJS", "--moduleResolution", "Node10");
run("--outDir", join(here, "dist/types"), "--declaration", "--emitDeclarationOnly");
writeFileSync(join(here, "dist/cjs/package.json"), JSON.stringify({ type: "commonjs" }) + "\n");
for (const f of ["cli.js", "ned-run.js"]) chmodSync(join(here, "dist/esm", f), 0o755);
console.log("built dist/esm, dist/cjs, dist/types");
