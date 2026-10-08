/** Ask before you call: is a host up, as Ned sees it from two continents? No key, no account.
 *   const r = await isUp("api.openai.com");   // { state: "up" | "degraded" | "down" | "reachable" | "unknown", ... }
 * "unknown" means the host is not on The Watch, never that it is down. Bad input (no host, a host that isn't a hostname,
 * a base URL without a scheme), a network problem or a reply that isn't a JSON object returns state "unknown" with an
 * error field rather than throwing, so a pre-flight check never breaks the call it guards. US first, then EU. */
import { REGIONS, VERSION } from "./client.js";

export interface UpResult { host: string; state: string; since?: string | null; reason?: string | null; watches?: unknown[]; ask_again_s?: number | null; error?: string; [k: string]: unknown }
export interface UpOptions { base?: string; timeoutMs?: number; ref?: string }

const HOST = /^(?!.*\.\.)[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?$/;   // [a-z0-9.-], alnum at both ends, no ".."

/** A host or URL reduced to a bare lowercase hostname, or the reason it isn't one. */
function cleanHost(host: unknown): { host: string; error?: string } {
  if (host === null || host === undefined) return { host: "", error: "host required" };
  if (typeof host !== "string") return { host: "", error: "bad host" };
  let h = host.trim();
  if (h.includes("://")) h = h.slice(h.indexOf("://") + 3);
  for (const sep of ["/", "?", "#"]) h = h.split(sep, 1)[0];
  h = h.split(":", 1)[0].toLowerCase();               // port
  if (!h) return { host: "", error: "host required" };
  if (!HOST.test(h)) return { host: h.slice(0, 253), error: "bad host" };
  return { host: h };
}

function errName(e: unknown): string {
  const n = e !== null && typeof e === "object" ? (e as { name?: unknown }).name : undefined;
  return typeof n === "string" && n ? n : "error";
}

export async function isUp(host: string, opts: UpOptions = {}): Promise<UpResult> {
  let h = "";
  try {
    const c = cleanHost(host);
    h = c.host;
    if (c.error) return { host: h, state: "unknown", error: c.error };
    const o: UpOptions = opts && typeof opts === "object" ? opts : {};
    const env = (typeof process !== "undefined" && process.env) || {};
    const bases: unknown[] = o.base ? [o.base] : [env.NED_API || env.NED_WATCH_API || REGIONS.us, REGIONS.eu];
    let err = "unreachable";
    for (const b of Array.from(new Set(bases))) {
      let t: ReturnType<typeof setTimeout> | undefined;
      try {
        const ctl = new AbortController();
        t = setTimeout(() => ctl.abort(), Number(o.timeoutMs) > 0 ? Number(o.timeoutMs) : 5000);
        const url = new URL(`${String(b).replace(/\/+$/, "")}/v1/up/${h}`);   // throws on a base without a scheme
        if (url.protocol !== "http:" && url.protocol !== "https:") throw new TypeError("base must be http(s)");
        const r = await fetch(url, { headers: { "User-Agent": `ned-watch-js/${VERSION}`, "X-Ned-Ref": String(o.ref || "js").replace(/[^\x20-\x7e]/g, "").slice(0, 32) || "js", Accept: "application/json" }, signal: ctl.signal });
        if (r.ok) {
          const reply: unknown = await r.json();
          if (reply && typeof reply === "object" && !Array.isArray(reply)) return reply as UpResult;
          err = "bad reply";
        } else err = `HTTP ${r.status}`;
      } catch (e) { err = errName(e); } finally { if (t !== undefined) clearTimeout(t); }
    }
    return { host: h, state: "unknown", error: err };
  } catch (e) {                                       // a pre-flight check never throws
    return { host: h, state: "unknown", error: errName(e) };
  }
}

export async function upState(host: string, opts: UpOptions = {}): Promise<string> {
  try { return String((await isUp(host, opts)).state || "unknown"); } catch { return "unknown"; }
}
