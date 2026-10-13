// Test-only helpers for the model tests (imported by *.test.ts files only).
import type { ReproEvent } from "@repro/events";
import { DEMO, FIXTURE_SEED, generateRun, type Profile } from "@repro/synth";
import { cloneState, type Projection } from "./projection";
import { EventStore } from "./store";

const cache = new Map<string, ReproEvent[]>();

/** A synthetic run's events (cached per profile and seed). Treat as read-only. */
export function runEvents(profile: Profile = DEMO, seed = FIXTURE_SEED): ReproEvent[] {
  const key = `${profile.name}/${seed}`;
  let events = cache.get(key);
  if (events === undefined) {
    events = generateRun(profile, seed).events;
    cache.set(key, events);
  }
  return events;
}

export function storeOf(events: readonly unknown[]): EventStore {
  const store = new EventStore();
  const result = store.appendAll(events);
  if (result.stopped !== undefined) {
    throw new Error(`ingestion stopped: ${JSON.stringify(result.stopped)}`);
  }
  return store;
}

/** Reference implementation: fold the first `k` events of the store from scratch, no snapshots. */
export function linearFold<S>(store: EventStore, projection: Projection<S>, k: number): S {
  let state = projection.init();
  for (let i = 0; i < k; i++) {
    const event = store.event(i);
    if (event !== null) {
      state = projection.apply(state, event, { index: i, time: store.time[i] as number });
    }
  }
  return cloneState(projection, state);
}

/** Copies events, renumbering `seq` from 1 (for streams with events inserted or removed). */
export function renumber(events: readonly object[]): object[] {
  return events.map((event, i) => ({ ...event, seq: i + 1 }));
}
