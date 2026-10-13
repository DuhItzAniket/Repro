import type { ReproEvent } from "@repro/events";

/** Where an event sits: its store index and presentation time (ms since the run started). */
export interface EventMeta {
  readonly index: number;
  readonly time: number;
}

/**
 * A pure reducer over the event stream (IMPLEMENTATION_PLAN §5). `apply` may mutate `state` and
 * must return the resulting state. It must not read clocks, random numbers or anything outside
 * its arguments, so folding the same events always gives the same state. That is what makes
 * snapshots, seeking and replay exact.
 */
export interface Projection<S> {
  readonly name: string;
  init(): S;
  apply(state: S, event: ReproEvent, meta: EventMeta): S;
  /** Deep copy for snapshots. Defaults to `structuredClone`, which covers plain data, Maps and Sets. */
  clone?(state: S): S;
}

export type StateOf<P> = P extends Projection<infer S> ? S : never;

export function cloneState<S>(projection: Projection<S>, state: S): S {
  return projection.clone === undefined ? structuredClone(state) : projection.clone(state);
}

/** Runs several projections side by side as one; each sees every event. */
export function combine<T extends Record<string, Projection<unknown>>>(
  name: string,
  parts: T,
): Projection<{ [K in keyof T]: StateOf<T[K]> }> {
  type S = { [K in keyof T]: StateOf<T[K]> };
  const entries = Object.entries(parts) as [keyof T & string, Projection<unknown>][];
  return {
    name,
    init: () => Object.fromEntries(entries.map(([key, p]) => [key, p.init()])) as S,
    apply: (state, event, meta) => {
      const record = state as Record<string, unknown>;
      for (const [key, p] of entries) record[key] = p.apply(record[key], event, meta);
      return state;
    },
    clone: (state) => {
      const record = state as Record<string, unknown>;
      return Object.fromEntries(entries.map(([key, p]) => [key, cloneState(p, record[key])])) as S;
    },
  };
}
