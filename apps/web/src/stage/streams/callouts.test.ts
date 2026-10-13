import { describe, expect, it } from "vitest";
import { CockpitModel } from "../../model/cockpit";
import { runEvents } from "../../model/test-support";
import { computeLayout } from "../../shell/layout";
import {
  CALLOUT_MS,
  CalloutTracker,
  calloutText,
  MAX_CALLOUTS,
  notable,
  selectCallouts,
} from "./callouts";

const model = new CockpitModel();
model.ingest(runEvents());
const { ring } = computeLayout(1440, 900);

describe("callouts", () => {
  it("agree with themselves: notable exactly when there is text", () => {
    for (let i = 0; i < model.store.length; i++) {
      const event = model.store.event(i);
      if (event !== null) expect(notable(event)).toBe(calloutText(event) !== null);
    }
  });

  it("label findings with one value", () => {
    const texts = runEvents()
      .map((e) => calloutText(e))
      .filter((t) => t !== null)
      .map((t) => `${t.label}: ${t.value}`);
    expect(texts).toEqual(
      expect.arrayContaining([
        "C3 contradicted: 2 evidence",
        "C2 rejected: quote mismatch",
        "behaviour: format_duration",
        "P2F: test_format_duration_hours",
        "test change: skip added",
        "dependency: example-tzdb added",
        "perf: ×0.49",
        "no new dependencies: fail",
        "card: FLAGGED",
      ]),
    );
  });

  it("show at most two, the newest first, each for 2.5 s", () => {
    const timeOf = new Map<string, number>();
    for (let i = 0; i < model.store.length; i++) {
      timeOf.set(model.store.envelope(i).id, model.store.time[i] as number);
    }
    for (let t = 0; t <= model.store.endTime; t += 200) {
      const shown = selectCallouts(model, t, ring);
      expect(shown.length).toBeLessThanOrEqual(MAX_CALLOUTS);
      const times = shown.map((c) => timeOf.get(c.key) ?? Number.NaN);
      for (const time of times) {
        expect(time).toBeLessThanOrEqual(t);
        expect(t - time).toBeLessThanOrEqual(CALLOUT_MS);
      }
      expect(times).toEqual([...times].sort((a, b) => b - a));
      if (shown.length === 2) {
        expect(Math.abs((shown[0]?.y ?? 0) - (shown[1]?.y ?? 0))).toBeGreaterThanOrEqual(26 - 1e-9);
      }
    }
  });

  it("re-render only when the visible set changes", () => {
    const tracker = new CalloutTracker();
    const first = tracker.update(model, 30_500, ring);
    expect(first?.map((c) => c.label)).toEqual(["F2P", "F2P"]);
    expect(tracker.update(model, 30_510, ring)).toBeNull();
    expect(tracker.update(model, 30_510, { ...ring, r: ring.r + 1 })).not.toBeNull(); // resized
    expect(tracker.update(model, 34_000, ring)?.map((c) => c.label)).toEqual([
      "no new dependencies",
      "missing",
    ]);
  });
});
