import { createHmac, timingSafeEqual } from "node:crypto";

/** Check that a callback really came from Ned: X-Ned-Signature = hex(HMAC-SHA256(secret, timestamp + "." + raw_body)).
 *  Pass the raw body exactly as received (string or Buffer), not re-serialized JSON. */
export function verifySignature(signingSecret: string, headers: Record<string, string | string[] | undefined> | Headers,
                                rawBody: string | Uint8Array, toleranceS = 300, now = Date.now() / 1000): boolean {
  const get = (k: string): string => {
    if (typeof (headers as Headers).get === "function") return (headers as Headers).get(k) || "";
    const h = headers as Record<string, string | string[] | undefined>;
    const key = Object.keys(h).find((x) => x.toLowerCase() === k);
    const v = key ? h[key] : undefined;
    return Array.isArray(v) ? v[0] || "" : v || "";
  };
  const ts = get("x-ned-timestamp"), sig = get("x-ned-signature").trim().toLowerCase();
  if (!/^\d+$/.test(ts) || !sig || Math.abs(now - parseInt(ts, 10)) > toleranceS) return false;
  const body = typeof rawBody === "string" ? Buffer.from(rawBody) : Buffer.from(rawBody);
  const want = createHmac("sha256", signingSecret).update(Buffer.concat([Buffer.from(ts + "."), body])).digest("hex");
  return want.length === sig.length && timingSafeEqual(Buffer.from(want), Buffer.from(sig));
}
