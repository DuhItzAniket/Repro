import fc from "fast-check";
import { describe, expect, it } from "vitest";
import type { RingCard } from "./content";
import { easeOutCubic, ringAngles, ringRotation, SNAP_MS } from "./rotation";

const TAU = Math.PI * 2;
const card = (weight: number): RingCard => ({
  file: `f${weight}`,
  lines: [],
  meta: [],
  weight,
  appear: 0,
  blastAt: 0,
  changedAt: 0,
});
const cards = [3, 5, 2, 8, 4, 6, 1, 7].map(card);
const angles = ringAngles(cards);
const centre = (i: number) => ((angles.start[i] as number) + (angles.end[i] as number)) / 2;
/** Screen angle of card i's centre at time t, wrapped to (−π, π]. */
function screenAngle(rotation: ReturnType<typeof ringRotation>, i: number, t: number): number {
  let a = (centre(i) + rotation.at(t)) % TAU;
  if (a <= -Math.PI) a += TAU;
  if (a > Math.PI) a -= TAU;
  return a;
}

describe("ringAngles", () => {
  it("shares the circle in proportion to weight, without gaps", () => {
    expect(angles.start[0]).toBe(0);
    expect(angles.end[cards.length - 1]).toBeCloseTo(TAU, 12);
    for (let i = 1; i < cards.length; i++) expect(angles.start[i]).toBe(angles.end[i - 1]);
    const total = cards.reduce((s, c) => s + c.weight, 0);
    expect((angles.end[3] as number) - (angles.start[3] as number)).toBeCloseTo(
      (8 / total) * TAU,
      12,
    );
  });

  it("drifts by one card per 2 s", () => {
    expect(angles.drift * 2000).toBeCloseTo(TAU / cards.length, 12);
  });
});

describe("ringRotation (B06: snap timing)", () => {
  const focus = [
    { time: 1_000, card: 3 },
    { time: 4_000, card: 6 },
    { time: 4_200, card: 1 }, // starts while the previous snap is still running
  ];
  const rotation = ringRotation(angles, focus);

  it("drifts alone before the first focus event", () => {
    expect(rotation.at(500)).toBeCloseTo(angles.drift * 500, 12);
  });

  it("puts the focused card at 3 o'clock exactly 500 ms after its event", () => {
    expect(screenAngle(rotation, 3, 1_000 + SNAP_MS)).toBeCloseTo(0, 9);
    expect(screenAngle(rotation, 1, 4_200 + SNAP_MS)).toBeCloseTo(0, 9);
  });

  it("follows ease-out-cubic between start and end", () => {
    const start = rotation.at(1_000) - angles.drift * 1_000;
    const end = rotation.at(1_500) - angles.drift * 1_500;
    for (const f of [0.1, 0.25, 0.5, 0.75]) {
      const t = 1_000 + f * SNAP_MS;
      const offset = rotation.at(t) - angles.drift * t;
      expect(offset).toBeCloseTo(start + (end - start) * easeOutCubic(f), 10);
    }
    expect(easeOutCubic(0.5)).toBe(0.875);
  });

  it("never jumps, including when a snap interrupts another", () => {
    let previous = rotation.at(0);
    for (let t = 1; t <= 6_000; t++) {
      const now = rotation.at(t);
      expect(Math.abs(now - previous)).toBeLessThan(0.02);
      previous = now;
    }
  });

  it("is a pure function of t (any order of queries)", () => {
    fc.assert(
      fc.property(
        fc.array(fc.integer({ min: 0, max: 8_000 }), { minLength: 1, maxLength: 30 }),
        (times) => {
          const fresh = ringRotation(angles, focus);
          for (const t of times) expect(fresh.at(t)).toBe(rotation.at(t));
        },
      ),
    );
  });

  it("turns the short way round", () => {
    const delta = Math.abs(
      rotation.at(1_500) - angles.drift * 1_500 - (rotation.at(1_000) - angles.drift * 1_000),
    );
    expect(delta).toBeLessThanOrEqual(Math.PI + 1e-9);
  });

  it("snaps instantly when motion is off (snap of 0 ms)", () => {
    const instant = ringRotation(angles, focus, 0);
    expect(screenAngle(instant, 3, 1_000)).toBeCloseTo(angles.drift * 0, 9);
  });
});
