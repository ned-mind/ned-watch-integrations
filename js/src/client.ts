// The Ned Watch client for Node. Zero dependencies (global fetch, Node >= 18.17).
import { randomBytes } from "node:crypto";
import { State, WatchRecord } from "./state.js";
import { Duration, errorSummary, fingerprint, seconds, slug } from "./util.js";
import { defaultName, detectFramework } from "./detect.js";

export const VERSION = "0.1.2";
export const REGIONS = { us: "https://api.ned.watch", eu: "https://api-eu.ned.watch" } as const;
const REGISTER_TIMEOUT_MS = 75_000;          // Ned delivers the signed test callback before it answers a new registration
const RETRYABLE = new Set([429, 500, 502, 503, 504]);

export class NedError extends Error {
  constructor(message: string, public status: number | null = null, public detail: unknown = null) {
    super(message);
    this.name = "NedError";
  }
}

export class NedConfigError extends NedError {
  constructor(message: string) {
    super(message);
    this.name = "NedConfigError";
  }
}

export interface NedOptions {
  /** nw_... Default: $NED_AGENT_KEY, else the one saved in the state file. With none, your first registration makes one. */
  agentKey?: string;
  /** API base. Default: $NED_API (or $NED_WATCH_API), else by region. */
  base?: string;
  /** "us" (default) or "eu". Default: $NED_REGION. */
  region?: "us" | "eu";
  /** Where Ned POSTs signed fire/clear messages. Default: $NED_CALLBACK_URL. */
  callbackUrl?: string;
  /** Integration tag sent as X-Ned-Ref. Default: $NED_REF, else the detected framework, else "js". */
  ref?: string;
  /** State file path, or false to keep nothing on disk. Default: $NED_STATE or ~/.config/ned-watch/state.json */
  state?: string | false;
  timeoutMs?: number;
  retries?: number;
  /** false (default): wrap()/run() never let a Ned problem break your job; they warn. true: they throw. */
  strict?: boolean;
  /** Where warnings go. Default: console.warn */
  logger?: (msg: string) => void;
}

type Json = Record<string, any>;
type WatchRef = string | Handle;

function cleanRef(ref: string): string {
  return ref.trim().toLowerCase().slice(0, 32).replace(/[^a-z0-9._-]/g, "") || "js";
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export class Ned {
  readonly base: string;
  readonly state: State;
  callbackUrl?: string;
  timeoutMs: number;
  retries: number;
  strict: boolean;
  private key?: string;
  private refExplicit?: string;
  private log: (msg: string) => void;

  constructor(opts: NedOptions = {}) {
    const region = (opts.region || process.env.NED_REGION || "us").toLowerCase() as "us" | "eu";
    if (!(region in REGIONS)) throw new Error("region must be 'us' or 'eu'");
    this.base = (opts.base || process.env.NED_API || process.env.NED_WATCH_API || REGIONS[region]).replace(/\/+$/, "");
    this.state = new State(opts.state);
    this.key = opts.agentKey || process.env.NED_AGENT_KEY || this.state.agentKey(this.base);
    this.callbackUrl = opts.callbackUrl || process.env.NED_CALLBACK_URL;
    this.refExplicit = opts.ref || process.env.NED_REF;
    this.timeoutMs = opts.timeoutMs ?? 15_000;
    this.retries = opts.retries ?? 2;
    this.strict = !!opts.strict;
    this.log = opts.logger || ((m) => console.warn(m));
  }

  get ref(): string { return cleanRef(this.refExplicit || detectFramework() || "js"); }
  get hasKey(): boolean { return !!this.key; }
  /** Integrations call this: their name becomes the ref unless the caller set one. */
  defaultRef(ref: string): this { if (!this.refExplicit) this.refExplicit = ref; return this; }
  toString(): string { return `Ned(base=${this.base}, ref=${this.ref}, key=${this.key ? "set" : "none"})`; }

  // ---------- HTTP ----------

  private headers(bearer?: string): Record<string, string> {
    const h: Record<string, string> = { "User-Agent": `ned-watch-js/${VERSION}`, "X-Ned-Ref": this.ref, Accept: "application/json" };
    if (bearer) h.Authorization = `Bearer ${bearer}`;
    return h;
  }

  /** One API call with retries on network errors and 429/5xx. Throws NedError. */
  async call(method: string, path: string, o: { bearer?: string; body?: Json; timeoutMs?: number; retries?: number } = {}): Promise<any> {
    const tries = 1 + (o.retries ?? this.retries);
    let last: NedError | null = null;
    for (let i = 0; i < tries; i++) {
      let res: Response | null = null;
      try {
        const h = this.headers(o.bearer);
        if (o.body !== undefined) h["Content-Type"] = "application/json";
        res = await fetch(this.base + path, {
          method, headers: h, body: o.body !== undefined ? JSON.stringify(o.body) : undefined,
          signal: AbortSignal.timeout(o.timeoutMs ?? this.timeoutMs),
        });
      } catch (e: any) {
        last = new NedError(`couldn't reach Ned at ${this.base}: ${e?.cause?.code || e?.name || e}`);
      }
      if (res) {
        const text = await res.text();
        let parsed: any = {};
        try { parsed = text ? JSON.parse(text) : {}; } catch { parsed = { raw: text.slice(0, 500) }; }
        if (res.ok) return parsed;
        const detail = parsed && typeof parsed === "object" && "detail" in parsed ? parsed.detail : parsed;
        const msg = detail && typeof detail === "object" && detail.error ? detail.error : JSON.stringify(detail);
        last = new NedError(`Ned answered HTTP ${res.status} to ${method} ${path.split("?")[0]}: ${msg}`, res.status, detail);
        const ra = res.headers.get("retry-after");
        if (!RETRYABLE.has(res.status) || (ra && /^\d+$/.test(ra) && parseInt(ra, 10) > 10)) throw last;
      }
      if (i < tries - 1) await sleep(Math.min(10_000, 500 * 3 ** i));
    }
    throw last!;
  }

  // ---------- registration ----------

  /** @internal */
  body(type: string, callbackUrl: string | undefined, fields: Json): Json {
    const cb = callbackUrl || this.callbackUrl;
    if (!cb) {
      throw new NedConfigError("no callback URL: pass callbackUrl or set NED_CALLBACK_URL (a free test one: https://webhook.site). " +
        "Ned POSTs signed fire/clear messages there.");
    }
    const b: Json = { type, callback_url: cb };
    for (const [k, v] of Object.entries(fields)) if (v !== undefined && v !== null) b[k] = v;
    return b;
  }

  private afterRegister(slot: string | null, body: Json, res: Json, serverArmed = false): WatchRecord {
    if (res.agent_key) {
      this.key = res.agent_key;
      this.state.setAgentKey(this.base, res.agent_key);
    }
    const tc = res.test_callback;
    if (tc && !tc.delivered) this.log(`Ned couldn't deliver the test callback for ${res.watch_id}: ${tc.problem || tc.status}`);
    const rec: WatchRecord = { id: res.watch_id, secret: res.signing_secret, fp: fingerprint(body), type: body.type, new: !res.existing };
    if (serverArmed) rec.armed = true;        // v1.9: condition.arm started the clock at registration
    if (slot) this.state.setWatch(this.base, slot, rec);
    return rec;
  }

  /** POST /v1/watches as is (any type). The agent_key in the answer is saved to the state file. */
  async register(type: string, fields: { callbackUrl?: string; interval_s?: number; target?: string; condition?: Json;
    max_runtime_s?: number; expect?: Json } = {}): Promise<Json> {
    const { callbackUrl, ...rest } = fields;
    const body = this.body(type, callbackUrl, { ...rest, condition: rest.condition && Object.keys(rest.condition).length ? rest.condition : undefined });
    if (!this.key) body.meta = { ref: this.ref };
    const res = await this.call("POST", "/v1/watches", { bearer: this.key, body, timeoutMs: REGISTER_TIMEOUT_MS, retries: this.key ? undefined : 0 });
    this.afterRegister(null, body, res);
    return res;
  }

  /** @internal */
  async ensure(slot: string, body: Json, force = false): Promise<WatchRecord> {
    const fp = fingerprint(body);
    const old = this.state.watch(this.base, slot);
    if (old && old.fp === fp && !force) return old;
    let b = this.key ? body : { ...body, meta: { ref: this.ref } };
    const post = (x: Json) => this.call("POST", "/v1/watches", { bearer: this.key, body: x, timeoutMs: REGISTER_TIMEOUT_MS, retries: this.key ? undefined : 0 });
    let res: Json;
    try {
      res = await post(b);
    } catch (e) {
      // A server that refuses condition.arm: register without it; the client arms with a first check-in instead.
      if (!(e instanceof NedError) || e.status !== 422 || !b.condition?.arm || !JSON.stringify(e.detail ?? "").includes("arm")) throw e;
      const { arm: _arm, ...cond } = b.condition;
      b = { ...b, condition: cond };
      res = await post(b);
    }
    const rec = this.afterRegister(slot, body, res, !!b.condition?.arm);
    if (old && old.id !== rec.id && this.key) {        // same name, new settings: cancel the old watch so it doesn't fire
      await this.call("DELETE", `/v1/watches/${old.id}`, { bearer: this.key, retries: 0 })
        .catch((e) => this.log(`couldn't cancel the previous watch ${old.id}: ${e.message}`));
    }
    return rec;
  }

  // ---------- handles ----------

  /** A deadman named `name`: Ned fires if no check-in arrives within `every`. Registered on first use, then reused. */
  deadman(name?: string, opts: { every?: Duration; grace?: Duration; callbackUrl?: string } = {}): Deadman {
    return new Deadman(this, name || defaultName(), seconds(opts.every ?? "1h"), opts.grace !== undefined ? seconds(opts.grace) : undefined, opts.callbackUrl);
  }

  /** An overrun named `name`: Ned fires if a run is still open `max` after start(). */
  overrun(name?: string, opts: { max?: Duration; callbackUrl?: string } = {}): Overrun {
    return new Overrun(this, name || defaultName(), seconds(opts.max ?? "1h"), opts.callbackUrl);
  }

  /** Run `fn` as one watched run: start, then finish when it resolves. With `every`, also a deadman checked in after
   *  each clean run. On a throw: onError "report" (default) finishes the run with status "failed" and a short error
   *  (name + first line, credentials redacted, <= 200 chars), so Ned fires at once; "leave_open" leaves it open (Ned
   *  fires when max passes); "finish" closes it as ok. "auto" is an alias of "report". */
  async run<T>(name: string | undefined, opts: RunOptions, fn: () => T | Promise<T>): Promise<T> {
    const nm = name || defaultName();
    const ow = this.overrun(nm, { max: opts.max ?? "1h", callbackUrl: opts.callbackUrl });
    const dm = opts.every !== undefined ? this.deadman(nm, { every: opts.every, callbackUrl: opts.callbackUrl }) : undefined;
    const onError = opts.onError ?? "report";
    if (!["report", "auto", "leave_open", "finish"].includes(onError)) throw new Error("onError must be 'report', 'leave_open' or 'finish'");
    if (dm) await dm.arm();
    const runId = opts.runId || `${ow.name.slice(0, 40)}-${randomBytes(6).toString("hex")}`;
    const started = await this.soft(`start of ${ow.name}`, () => ow.start(runId));
    let out: T;
    try {
      out = await fn();
    } catch (e: any) {
      if (started && onError !== "leave_open") {
        const fail = onError === "finish" ? {} : { failed: true, error: e?.nedError ?? errorSummary(e) };
        await this.soft(`finish of ${ow.name}`, () => ow.finish(runId, fail));
      }
      throw e;
    }
    if (started) await this.soft(`finish of ${ow.name}`, () => ow.finish(runId));
    if (dm) await this.soft(`check-in for ${dm.name}`, () => dm.checkin());
    return out;
  }

  // ---------- direct calls ----------

  private async secretFor(watch: WatchRef, signingSecret?: string): Promise<[string, string]> {
    if (watch instanceof Handle) {
      const rec = await watch.ensure();
      return [rec.id, signingSecret || rec.secret];
    }
    const id = String(watch);
    if (!id.startsWith("w_")) {
      const rec = this.state.watch(this.base, `deadman:${slug(id)}`) || this.state.watch(this.base, `overrun:${slug(id)}`);
      if (!rec) throw new NedConfigError(`no watch named '${id}' in ${this.state.path || "memory"}; register it first`);
      return [rec.id, signingSecret || rec.secret];
    }
    if (signingSecret) return [id, signingSecret];
    const rec = this.state.byId(this.base, id);
    if (rec) return [id, rec.secret];
    if (process.env.NED_SIGNING_SECRET && (process.env.NED_WATCH_ID || id) === id) return [id, process.env.NED_SIGNING_SECRET];
    throw new NedConfigError(`no signing secret for ${id}: pass signingSecret or set NED_SIGNING_SECRET`);
  }

  /** POST /v1/checkin/{id}. `watch`: a watch id (w_...), a name this client registered, or a Deadman. */
  async checkin(watch: WatchRef, signingSecret?: string): Promise<Json> {
    const [id, sec] = await this.secretFor(watch, signingSecret);
    return this.call("POST", `/v1/checkin/${id}`, { bearer: sec });
  }

  async start(watch: WatchRef, runId?: string, signingSecret?: string): Promise<Json> {
    const [id, sec] = await this.secretFor(watch, signingSecret);
    return this.call("POST", `/v1/watches/${id}/start`, { bearer: sec, body: runId ? { run_id: runId } : {} });
  }

  /** POST /finish. `failed: true` reports the run as crashed: Ned fires at once, with `error` (<= 200 chars). */
  async finish(watch: WatchRef, runId?: string, signingSecret?: string, opts: FinishOptions = {}): Promise<Json> {
    const [id, sec] = await this.secretFor(watch, signingSecret);
    const body: Json = runId ? { run_id: runId } : {};
    if (opts.failed) {
      body.status = "failed";
      if (opts.error) body.error = errorSummary(opts.error);
    }
    return this.call("POST", `/v1/watches/${id}/finish`, { bearer: sec, body });
  }

  private needKey(): string {
    if (!this.key) throw new NedConfigError("this call needs your agent key: set NED_AGENT_KEY (your first registration issues it)");
    return this.key;
  }

  get(watchId: string): Promise<Json> { return this.call("GET", `/v1/watches/${watchId}`, { bearer: this.needKey() }); }
  watches(): Promise<Json[]> { return this.call("GET", "/v1/watches", { bearer: this.needKey() }); }
  balance(): Promise<Json> { return this.call("GET", "/v1/balance", { bearer: this.needKey() }); }
  health(): Promise<Json> { return this.call("GET", "/health", { retries: 0 }); }

  async cancel(watchId: string): Promise<void> {
    await this.call("DELETE", `/v1/watches/${watchId}`, { bearer: this.needKey() });
    for (const [slot, rec] of Object.entries(this.state.watches(this.base))) if (rec.id === watchId) this.state.setWatch(this.base, slot, null);
  }

  /** @internal fail-open: Ned problems become warnings unless strict. */
  async soft<T>(what: string, fn: () => Promise<T>): Promise<T | null> {
    try {
      return await fn();
    } catch (e: any) {
      if (this.strict || !(e instanceof NedError)) throw e;
      this.log(`Ned Watch ${what} failed (your job is unaffected): ${e.message}`);
      return null;
    }
  }
}

export interface RunOptions { max?: Duration; every?: Duration; runId?: string; onError?: "report" | "auto" | "leave_open" | "finish"; callbackUrl?: string }
export interface FinishOptions { failed?: boolean; error?: string }

export abstract class Handle {
  readonly name: string;
  protected rec: WatchRecord | null = null;
  abstract readonly kind: string;

  constructor(readonly ned: Ned, name: string, readonly callbackUrl?: string) { this.name = slug(name); }

  get slot(): string { return `${this.kind}:${this.name}`; }
  get id(): string | undefined { return this.rec?.id; }
  protected abstract fields(): Json;

  /** Register the watch if this client hasn't yet (or reuse the identical one). */
  async ensure(force = false): Promise<WatchRecord> {
    if (!this.rec || force) this.rec = await this.ned.ensure(this.slot, this.ned.body(this.kind, this.callbackUrl, this.fields()), force);
    return this.rec;
  }

  async cancel(): Promise<void> {
    const r = await this.ensure();
    await this.ned.cancel(r.id);
    this.rec = null;
  }

  /** A watch cancelled elsewhere answers 404: register it again once and retry. */
  protected async retryGone<T>(fn: () => Promise<T>): Promise<T> {
    try {
      return await fn();
    } catch (e) {
      if (!(e instanceof NedError) || e.status !== 404) throw e;
      await this.ensure(true);
      return fn();
    }
  }

  toString(): string { return `${this.constructor.name}(${this.name}, ${this.rec?.id ?? "unregistered"})`; }
  toJSON(): Json { return { kind: this.kind, name: this.name, id: this.rec?.id ?? null }; }   // never the secret
}

export class Deadman extends Handle {
  readonly kind = "deadman";
  private lastBeat = -Infinity;

  constructor(ned: Ned, name: string, readonly everyS: number, readonly graceS?: number, callbackUrl?: string) {
    super(ned, name, callbackUrl);
  }

  protected fields(): Json {
    const condition: Json = { label: this.name, arm: true };       // v1.9: the clock starts at registration
    if (this.graceS !== undefined) condition.grace_s = this.graceS;
    return { interval_s: this.everyS, condition };
  }

  async checkin(): Promise<Json> {
    await this.ensure();
    const out = await this.retryGone(() => this.ned.checkin(this));
    if (this.rec && !this.rec.armed) {
      this.rec = { ...this.rec, armed: true };
      this.ned.state.setWatch(this.ned.base, this.slot, this.rec);
    }
    return out;
  }

  /** Make sure the watch exists and its clock runs (Ned's clock starts at the first check-in, so a job whose very first
   *  run fails would otherwise never be noticed). Checks in the first time only. Never throws (unless strict). */
  async arm(): Promise<this> {
    await this.ned.soft(`arming ${this.name}`, async () => {
      const r = await this.ensure();
      if (r.armed) return;
      if (r.new || (await this.ned.get(r.id)).last_checkin == null) await this.checkin();
      else {                                   // existing and checked in before (e.g. a container with no state file)
        this.rec = { ...r, armed: true };
        this.ned.state.setWatch(this.ned.base, this.slot, this.rec);
      }
    });
    return this;
  }

  /** A throttled, never-throwing check-in for progress events. At most one per `minIntervalS` (Ned allows 60/min).
   *  A beat counts as alive, so on a job that works and then fails it can hide the failure: use it for long-lived loops. */
  async beat(minIntervalS = 30): Promise<Json | null> {
    const now = performance.now() / 1000;
    if (now - this.lastBeat < minIntervalS) return null;
    this.lastBeat = now;
    return this.ned.soft(`heartbeat for ${this.name}`, () => this.checkin()).catch(() => null);
  }

  /** Wrap a function: arm before, check in after each call that returns (or resolves) without throwing. */
  wrap<A extends unknown[], R>(fn: (...args: A) => R | Promise<R>): (...args: A) => Promise<R> {
    return async (...args: A) => {
      await this.arm();
      const out = await fn(...args);
      await this.ned.soft(`check-in for ${this.name}`, () => this.checkin());
      return out;
    };
  }
}

export class Overrun extends Handle {
  readonly kind = "overrun";

  constructor(ned: Ned, name: string, readonly maxS: number, callbackUrl?: string) { super(ned, name, callbackUrl); }

  protected fields(): Json { return { max_runtime_s: this.maxS, condition: { label: this.name } }; }

  async start(runId?: string): Promise<Json> {
    await this.ensure();
    return this.retryGone(() => this.ned.start(this, runId));
  }

  async finish(runId?: string, opts: FinishOptions = {}): Promise<Json> {
    await this.ensure();
    return this.ned.finish(this, runId, undefined, opts);
  }
}
