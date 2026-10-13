import type { AgentId, EventKind, ReproEvent, Stage, Status, Target } from "@repro/events";
import { isoTime, ulid } from "./ids";
import type { Rng } from "./rng";

export type EventOf<K extends EventKind> = Extract<ReproEvent, { kind: K }>;
export type PayloadOf<K extends EventKind> = EventOf<K>["payload"];
export type StageOf<K extends EventKind> = EventOf<K>["stage"];

export interface EmitOptions {
  agent?: AgentId | null;
  target?: Target | null;
  /** Defaults to `ok`. */
  status?: Status;
  /** Causation. The parent must sort earlier than this event. */
  parent?: Draft | null;
}

/** An event before the single writer has ordered it: no seq, no id yet. */
export interface Draft {
  /** Milliseconds since the run started. */
  readonly at: number;
  /** Emission order; breaks ties between drafts with the same `at`. */
  readonly order: number;
  readonly kind: EventKind;
  readonly stage: Stage;
  readonly agent: AgentId | null;
  readonly target: Target | null;
  readonly status: Status;
  readonly payload: unknown;
  readonly parent: Draft | null;
}

export interface BuildOptions {
  /** Epoch milliseconds of the run start (`at = 0`). */
  startMs: number;
  runId: string;
  producer: string;
  /** Stream for the random part of event ULIDs. */
  ids: Rng;
}

/**
 * Collects drafts in any order, then plays the single writer (ADR-0002): sorts them by time,
 * assigns `seq` from 1 with no gaps, gives each a ULID, and resolves `parent` links.
 */
export class Timeline {
  private readonly drafts: Draft[] = [];

  get size(): number {
    return this.drafts.length;
  }

  emit<K extends EventKind>(
    at: number,
    kind: K,
    stage: StageOf<K>,
    payload: PayloadOf<K>,
    options: EmitOptions = {},
  ): Draft {
    if (!Number.isInteger(at) || at < 0) {
      throw new RangeError(`${kind}: event time must be a non-negative integer ms, got ${at}`);
    }
    const draft: Draft = {
      at,
      order: this.drafts.length,
      kind,
      stage,
      agent: options.agent ?? null,
      target: options.target ?? null,
      status: options.status ?? "ok",
      payload,
      parent: options.parent ?? null,
    };
    this.drafts.push(draft);
    return draft;
  }

  count(predicate: (draft: Draft) => boolean): number {
    return this.drafts.filter(predicate).length;
  }

  build(options: BuildOptions): ReproEvent[] {
    const ordered = [...this.drafts].sort((x, y) => x.at - y.at || x.order - y.order);
    const ids = new Map<Draft, string>();
    return ordered.map((draft, index) => {
      const id = `evt_${ulid(options.startMs + draft.at, options.ids)}`;
      ids.set(draft, id);
      let parent: string | undefined;
      if (draft.parent !== null) {
        parent = ids.get(draft.parent);
        if (parent === undefined) {
          throw new Error(
            `${draft.kind} at ${draft.at} ms sorts before its parent ${draft.parent.kind} at ${draft.parent.at} ms`,
          );
        }
      }
      // Key order is fixed so the serialised log is byte-stable.
      return {
        id,
        run_id: options.runId,
        seq: index + 1,
        ts: isoTime(options.startMs + draft.at),
        stage: draft.stage,
        agent: draft.agent,
        kind: draft.kind,
        target: draft.target,
        status: draft.status,
        payload: draft.payload,
        v: 1,
        pv: 1,
        ...(parent === undefined ? {} : { parent }),
        producer: options.producer,
      } as ReproEvent;
    });
  }
}
