/** Ned Watch for Node: know when your agent silently stops. https://ned.watch/integrations/js */
export { Ned, Deadman, Overrun, Handle, NedError, NedConfigError, VERSION, REGIONS } from "./client.js";
export type { NedOptions, RunOptions, FinishOptions } from "./client.js";
export { verifySignature } from "./verify.js";
export { detectFramework, defaultName } from "./detect.js";
export { seconds, slug, fingerprint, canonicalJson, errorSummary, redact } from "./util.js";
export type { Duration } from "./util.js";
export { State, defaultStatePath } from "./state.js";
export type { WatchRecord } from "./state.js";
