// Where the client remembers its agent key and the watches it registered. Same file and format as the Python client:
// $NED_STATE, else ~/.config/ned-watch/state.json (mode 0600).
// {"<api base>": {"agent_key": "...", "watches": {"deadman:<name>": {"id", "secret", "fp", "type", "armed"}}}}
import { chmodSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { randomBytes } from "node:crypto";

export interface WatchRecord { id: string; secret: string; fp: string; type: string; armed?: boolean; new?: boolean }
type Data = Record<string, { agent_key?: string; watches?: Record<string, WatchRecord> }>;

export function defaultStatePath(): string {
  if (process.env.NED_STATE) return process.env.NED_STATE;
  const root = process.env.XDG_CONFIG_HOME || join(homedir(), ".config");
  return join(root, "ned-watch", "state.json");
}

export class State {
  readonly path: string | null;
  private mem: Data = {};

  constructor(where?: string | false) {
    this.path = where === false ? null : where || defaultStatePath();
  }

  private load(): Data {
    if (!this.path) return this.mem;
    try {
      const d = JSON.parse(readFileSync(this.path, "utf8"));
      return d && typeof d === "object" ? d : {};
    } catch {
      return {};
    }
  }

  private save(d: Data): void {
    if (!this.path) { this.mem = d; return; }
    mkdirSync(dirname(this.path), { recursive: true, mode: 0o700 });
    const tmp = join(dirname(this.path), `.state-${randomBytes(6).toString("hex")}`);
    writeFileSync(tmp, JSON.stringify(d, null, 1), { mode: 0o600 });
    chmodSync(tmp, 0o600);
    renameSync(tmp, this.path);
  }

  agentKey(base: string): string | undefined { return this.load()[base]?.agent_key; }

  setAgentKey(base: string, key: string): void {
    const d = this.load();
    (d[base] ??= {}).agent_key = key;
    this.save(d);
  }

  watch(base: string, slot: string): WatchRecord | undefined { return this.load()[base]?.watches?.[slot]; }

  byId(base: string, id: string): WatchRecord | undefined {
    return Object.values(this.load()[base]?.watches ?? {}).find((w) => w.id === id);
  }

  setWatch(base: string, slot: string, rec: WatchRecord | null): void {
    const d = this.load();
    const ws = ((d[base] ??= {}).watches ??= {});
    if (rec === null) delete ws[slot]; else ws[slot] = rec;
    this.save(d);
  }

  watches(base: string): Record<string, WatchRecord> { return { ...(this.load()[base]?.watches ?? {}) }; }
}
