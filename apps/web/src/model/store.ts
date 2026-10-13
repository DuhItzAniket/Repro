/**
 * The cockpit's append-only copy of one run's event log (ARCHITECTURE §13).
 *
 * Columns live in typed arrays so time and kind queries over 100k events stay cheap. The parsed
 * events themselves sit in a plain array next to them, for payload access. The store accepts
 * only a gap-free sequence: a duplicate `seq` (replay overlapping live) is ignored, and a gap
 * stops ingestion so the transport can resync from the expected `seq` (ARCHITECTURE §11).
 */
import type { Envelope, ReproEvent } from "@repro/events";
import { kindCode, SUPPORTED_ENVELOPE, stageCode, statusCode, UNKNOWN_KIND } from "./codes";

export type AppendOutcome =
  | { readonly status: "appended" }
  | { readonly status: "duplicate"; readonly seq: number }
  | { readonly status: "gap"; readonly expected: number; readonly got: number }
  | { readonly status: "rejected"; readonly reason: string };

export interface AppendSummary {
  readonly appended: number;
  readonly duplicates: number;
  /** Why ingestion stopped early (a gap or a rejected event); absent if everything was taken. */
  readonly stopped?: Exclude<AppendOutcome, { status: "appended" | "duplicate" }>;
}

const INITIAL_CAPACITY = 1024;

function grow<T extends Int8Array | Uint8Array | Int32Array | Float64Array>(
  column: T,
  capacity: number,
): T {
  const next = new (column.constructor as new (length: number) => T)(capacity);
  next.set(column);
  return next;
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

export class EventStore {
  /** `seq` per event (always index + 1 in a gap-free store; kept for assertions and export). */
  seq = new Int32Array(INITIAL_CAPACITY);
  /** Presentation time in ms since the run started: the running maximum of `ts`, so it never decreases. */
  time = new Float64Array(INITIAL_CAPACITY);
  kind = new Uint8Array(INITIAL_CAPACITY);
  stage = new Int8Array(INITIAL_CAPACITY);
  status = new Int8Array(INITIAL_CAPACITY);

  private readonly events: Envelope[] = [];
  private capacity = INITIAL_CAPACITY;
  private startMs = 0;
  private _runId: string | null = null;
  private _unknown = 0;
  private _version = 0;

  get length(): number {
    return this.events.length;
  }

  /** Increments on every append. Views compare it to decide whether to redraw. */
  get version(): number {
    return this._version;
  }

  get runId(): string | null {
    return this._runId;
  }

  /** Events whose kind (or payload version) this build cannot interpret. They are kept, not dropped. */
  get unknownCount(): number {
    return this._unknown;
  }

  /** Epoch ms of the first event, the origin of presentation time. */
  get origin(): number {
    return this.startMs;
  }

  /** Presentation time of the last event (0 when empty). */
  get endTime(): number {
    return this.length === 0 ? 0 : (this.time[this.length - 1] as number);
  }

  append(input: unknown): AppendOutcome {
    if (!isRecord(input)) return { status: "rejected", reason: "not a JSON object" };
    if (input.v !== SUPPORTED_ENVELOPE) {
      return { status: "rejected", reason: `unsupported envelope version ${String(input.v)}` };
    }
    const { seq, run_id: runId, ts, kind, stage, status, payload, pv } = input;
    if (typeof seq !== "number" || !Number.isInteger(seq) || seq < 1) {
      return { status: "rejected", reason: "seq is not a positive integer" };
    }
    const expected = this.length + 1;
    if (seq < expected) return { status: "duplicate", seq };
    if (seq > expected) return { status: "gap", expected, got: seq };
    if (typeof runId !== "string") return { status: "rejected", reason: "run_id is missing" };
    if (this._runId !== null && runId !== this._runId) {
      return { status: "rejected", reason: `event from run ${runId}, store holds ${this._runId}` };
    }
    const epochMs = typeof ts === "string" ? Date.parse(ts) : Number.NaN;
    if (!Number.isFinite(epochMs)) return { status: "rejected", reason: "ts is not a timestamp" };
    if (typeof kind !== "string" || typeof pv !== "number" || !isRecord(payload)) {
      return { status: "rejected", reason: "kind, pv or payload is malformed" };
    }
    const stageId = typeof stage === "string" ? stageCode(stage) : -1;
    const statusId = typeof status === "string" ? statusCode(status) : -1;
    if (stageId < 0 || statusId < 0) {
      return { status: "rejected", reason: "unknown stage or status" };
    }

    const i = this.length;
    if (i === this.capacity) {
      this.capacity *= 2;
      this.seq = grow(this.seq, this.capacity);
      this.time = grow(this.time, this.capacity);
      this.kind = grow(this.kind, this.capacity);
      this.stage = grow(this.stage, this.capacity);
      this.status = grow(this.status, this.capacity);
    }
    if (i === 0) {
      this._runId = runId;
      this.startMs = epochMs;
    }
    const code = kindCode(kind, pv);
    if (code === UNKNOWN_KIND) this._unknown++;
    this.seq[i] = seq;
    this.time[i] = Math.max(i === 0 ? 0 : (this.time[i - 1] as number), epochMs - this.startMs);
    this.kind[i] = code;
    this.stage[i] = stageId;
    this.status[i] = statusId;
    this.events.push(input as unknown as Envelope);
    this._version++;
    return { status: "appended" };
  }

  appendAll(inputs: Iterable<unknown>): AppendSummary {
    let appended = 0;
    let duplicates = 0;
    for (const input of inputs) {
      const outcome = this.append(input);
      if (outcome.status === "appended") appended++;
      else if (outcome.status === "duplicate") duplicates++;
      else return { appended, duplicates, stopped: outcome };
    }
    return { appended, duplicates };
  }

  /** The raw envelope at index `i` (any kind). */
  envelope(i: number): Envelope {
    const event = this.events[i];
    if (event === undefined) throw new RangeError(`no event at index ${i} (length ${this.length})`);
    return event;
  }

  /** The event at index `i` if this build understands its kind and payload version, else null. */
  event(i: number): ReproEvent | null {
    return this.kind[i] === UNKNOWN_KIND ? null : (this.envelope(i) as unknown as ReproEvent);
  }

  /** Number of events with presentation time ≤ t: the fold cursor for time t. */
  cursorAt(t: number): number {
    let lo = 0;
    let hi = this.length;
    while (lo < hi) {
      const mid = (lo + hi) >>> 1;
      if ((this.time[mid] as number) <= t) lo = mid + 1;
      else hi = mid;
    }
    return lo;
  }

  /** Index of the first event with presentation time ≥ t. */
  firstAtOrAfter(t: number): number {
    let lo = 0;
    let hi = this.length;
    while (lo < hi) {
      const mid = (lo + hi) >>> 1;
      if ((this.time[mid] as number) < t) lo = mid + 1;
      else hi = mid;
    }
    return lo;
  }
}
