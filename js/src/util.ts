import { createHash } from "node:crypto";

export type Duration = number | string;

const UNITS: Record<string, number> = { s: 1, m: 60, h: 3600, d: 86400, w: 604800 };

/** "90s", "20m", "1h", "1h30m", "1d" or a number of seconds -> whole seconds. */
export function seconds(v: Duration): number {
  if (typeof v === "number") {
    if (!Number.isFinite(v)) throw new Error("duration must be finite");
    return Math.trunc(v);
  }
  const s = String(v).trim().toLowerCase().replace(/\s+/g, "");
  if (/^\d+$/.test(s)) return parseInt(s, 10);
  const parts = [...s.matchAll(/(\d+(?:\.\d+)?)([smhdw])/g)];
  if (!parts.length || parts.map((p) => p[0]).join("") !== s) {
    throw new Error(`can't read duration ${JSON.stringify(v)}: use e.g. '90s', '20m', '1h', '1h30m', '1d'`);
  }
  return Math.trunc(parts.reduce((t, p) => t + parseFloat(p[1]) * UNITS[p[2]], 0));
}

/** A watch name as Ned's label rule wants it: 1-64 of A-Z a-z 0-9 . _ : - */
export function slug(name: string): string {
  const s = String(name).replace(/[^A-Za-z0-9._:-]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 64);
  if (!s) throw new Error(`watch name ${JSON.stringify(name)} has no usable characters (A-Z a-z 0-9 . _ : -)`);
  return s;
}

/** JSON with sorted keys, no spaces and non-ASCII escaped: byte-identical to Python's
 *  json.dumps(x, sort_keys=True, separators=(",", ":")), so both clients share one state file. */
export function canonicalJson(x: unknown): string {
  if (x === null || typeof x !== "object") {
    return JSON.stringify(x).replace(/[\u0080-\uffff]/g, (c) => "\\u" + c.charCodeAt(0).toString(16).padStart(4, "0"));
  }
  if (Array.isArray(x)) return "[" + x.map(canonicalJson).join(",") + "]";
  const o = x as Record<string, unknown>;
  return "{" + Object.keys(o).filter((k) => o[k] !== undefined).sort()
    .map((k) => canonicalJson(k) + ":" + canonicalJson(o[k])).join(",") + "}";
}

export function fingerprint(body: Record<string, unknown>): string {
  const { meta: _meta, ...rest } = body;
  return createHash("sha256").update(canonicalJson(rest)).digest("hex").slice(0, 16);
}

const SECRETS: [RegExp, string][] = [
  [/\b(nw|whs|sk|pk|rk|ghp|gho|ghs|github_pat|xox[abprs]|AKIA)[-_][A-Za-z0-9_\-]{6,}/g, "[redacted]"],
  [/\b(bearer|basic|token)\s+[A-Za-z0-9._~+/=\-]{8,}/gi, "$1 [redacted]"],
  [/([a-z][a-z0-9+.\-]*:\/\/)[^/\s:@]+:[^/\s@]+@/gi, "$1[redacted]@"],
  [/([?&;](?:[a-z_]*(?:token|key|secret|password|passwd|pwd|sig|signature|auth|credential)[a-z_]*)=)[^&\s;]+/gi, "$1[redacted]"],
  [/\b((?:[a-z_]*(?:token|secret|password|passwd|api_key|apikey))\s*[=:]\s*)\S+/gi, "$1[redacted]"],
  [/\b[A-Za-z0-9+/_\-]{32,}={0,2}/g, "[redacted]"],
];

export function redact(text: string): string {
  return SECRETS.reduce((t, [rx, sub]) => t.replace(rx, sub), text);
}

/** What Ned is told when a run fails: the error's name and the first line of its message, credentials removed,
 *  at most `limit` characters. Same rules as the Python client. */
export function errorSummary(err: unknown, limit = 200): string {
  let text: string;
  if (err instanceof Error) {
    const first = (String(err.message ?? "").trim().split(/\r?\n/)[0] || "");
    const name = err.name && err.name !== "Error" ? err.name : err.constructor?.name || "Error";
    text = first ? `${name}: ${first}` : name;
  } else {
    text = String(err ?? "").trim().split(/\r?\n/)[0] || "";
  }
  text = redact(text.replace(/[\x00-\x1f\x7f]/g, " "));
  return text.length <= limit ? text : text.slice(0, limit - 3) + "...";
}
