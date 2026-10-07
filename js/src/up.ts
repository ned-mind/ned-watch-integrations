/** Ask before you call: is a host up, as Ned sees it from two continents? No key, no account.
 *   const r = await isUp("api.openai.com");   // { state: "up" | "degraded" | "down" | "reachable" | "unknown", ... }
 * "unknown" means the host is not on The Watch, never that it is down. A network problem returns state "unknown" with an
 * error field rather than throwing, so a pre-flight check never breaks the call it guards. US first, then EU. */
import { REGIONS, VERSION } from "./client.js";

export interface UpResult { host: string; state: string; since?: string | null; reason?: string | null; watches?: unknown[]; ask_again_s?: number | null; error?: string; [k: string]: unknown }

export async function isUp(host: string, opts: { base?: string; timeoutMs?: number; ref?: string } = {}): Promise<UpResult> {
  let h = (host || "").trim();
  if (h.includes("://")) h = h.split("://", 2)[1];
  h = h.split("/", 1)[0].split("?", 1)[0].toLowerCase();
  if (!h) return { host: h, state: "unknown", error: "host required" };
  const env = (typeof process !== "undefined" && process.env) || {};
  const bases = opts.base ? [opts.base.replace(/\/+$/, "")] : [env.NED_API || env.NED_WATCH_API || REGIONS.us, REGIONS.eu];
  let err = "unreachable";
  for (const b of Array.from(new Set(bases))) {
    const ctl = new AbortController(); const t = setTimeout(() => ctl.abort(), opts.timeoutMs ?? 5000);
    try {
      const r = await fetch(`${b}/v1/up/${h}`, { headers: { "User-Agent": `ned-watch-js/${VERSION}`, "X-Ned-Ref": (opts.ref || "js").slice(0, 32), Accept: "application/json" }, signal: ctl.signal });
      if (r.ok) return (await r.json()) as UpResult;
      err = `HTTP ${r.status}`;
    } catch (e) { err = (e as Error).name || "error"; } finally { clearTimeout(t); }
  }
  return { host: h, state: "unknown", error: err };
}

export async function upState(host: string, opts: { base?: string; timeoutMs?: number; ref?: string } = {}): Promise<string> {
  return String((await isUp(host, opts)).state || "unknown");
}
