import fc from "fast-check";
import { describe, expect, it } from "vitest";
import {
  easeOutCubic,
  RING_TURN_MS,
  ringAngles,
  ringRotation,
  SNAP_MS,
  UNIT_ANGLE,
} from "./rotation";

const TAU = Math.PI * 2;
// Card sizes in band units: these eight overfill the circle, so they share it in proportion.
const card = (size: number) => ({ units: size * 200 });
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
  it("shares the circle in proportion to size when the cards overfill it, without gaps", () => {
    expect(angles.start[0]).toBe(0);
    expect(angles.end[cards.length - 1]).toBeCloseTo(TAU, 12);
    for (let i = 1; i < cards.length; i++) expect(angles.start[i]).toBe(angles.end[i - 1]);
    const total = cards.reduce((s, c) => s + c.units, 0);
    expect((angles.end[3] as number) - (angles.start[3] as number)).toBeCloseTo(
      ((8 * 200) / total) * TAU,
      12,
    );
  });

  it("gives each card its natural angle when they fit, leaving the rest of the band empty", () => {
    const few = ringAngles([{ units: 90 }, { units: 40 }]);
    expect(few.end[0]).toBeCloseTo(90 * UNIT_ANGLE, 12);
    expect(few.end[1]).toBeCloseTo(130 * UNIT_ANGLE, 12);
    expect(few.end[1] as number).toBeLessThan(TAU);
  });

  it("turns once per 24 s, the reference's measured speed (B14)", () => {
    expect(angles.drift * RING_TURN_MS).toBeCloseTo(TAU, 12);
    expect(ringAngles([]).drift).toBe(0);
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
