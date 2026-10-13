import fc from "fast-check";
import { describe, expect, it } from "vitest";
import { isoTime, ulid } from "./ids";
import { hash32, Rng } from "./rng";

const draw = (rng: Rng, n: number): number[] => Array.from({ length: n }, () => rng.next());

describe("Rng", () => {
  it("is a pure function of the seed", () => {
    fc.assert(
      fc.property(fc.nat({ max: 2 ** 32 - 1 }), (seed) => {
        expect(draw(new Rng(seed), 16)).toEqual(draw(new Rng(seed), 16));
      }),
    );
  });

  it("pins the first outputs of seed 1 (guards against accidental algorithm changes)", () => {
    expect(draw(new Rng(1), 4)).toMatchInlineSnapshot(`
      [
        1828152527,
        3394835397,
        2967886022,
        2251045104,
      ]
    `);
  });

  it("gives different streams for different seeds and fork names", () => {
    expect(draw(new Rng(1), 8)).not.toEqual(draw(new Rng(2), 8));
    const root = new Rng(7);
    expect(draw(root.fork("a"), 8)).not.toEqual(draw(root.fork("b"), 8));
  });

  it("forks depend on the seed and name, not on how much the parent has drawn", () => {
    const fresh = new Rng(42);
    const used = new Rng(42);
    draw(used, 100);
    expect(draw(used.fork("x"), 8)).toEqual(draw(fresh.fork("x"), 8));
  });

  it("keeps int() inside its inclusive bounds", () => {
    fc.assert(
      fc.property(
        fc.nat(),
        fc.integer({ min: -1000, max: 1000 }),
        fc.nat({ max: 1000 }),
        (seed, lo, span) => {
          const rng = new Rng(seed % 2 ** 32);
          for (let i = 0; i < 20; i++) {
            const value = rng.int(lo, lo + span);
            expect(value).toBeGreaterThanOrEqual(lo);
            expect(value).toBeLessThanOrEqual(lo + span);
            expect(Number.isInteger(value)).toBe(true);
          }
        },
      ),
    );
  });

  it("shuffles into a permutation", () => {
    fc.assert(
      fc.property(
        fc.nat({ max: 2 ** 32 - 1 }),
        fc.array(fc.integer(), { maxLength: 50 }),
        (seed, items) => {
          const out = new Rng(seed).shuffled(items);
          expect([...out].sort((a, b) => a - b)).toEqual([...items].sort((a, b) => a - b));
        },
      ),
    );
  });

  it("produces lowercase hex of the requested length", () => {
    const rng = new Rng(3);
    for (const length of [1, 7, 8, 40, 64])
      expect(rng.hex(length)).toMatch(new RegExp(`^[0-9a-f]{${length}}$`));
  });

  it("rejects seeds that are not uint32", () => {
    expect(() => new Rng(-1)).toThrow(RangeError);
    expect(() => new Rng(2 ** 32)).toThrow(RangeError);
    expect(() => new Rng(1.5)).toThrow(RangeError);
  });

  it("hash32 is FNV-1a (published test vectors)", () => {
    expect(hash32("")).toBe(0x811c9dc5);
    expect(hash32("a")).toBe(0xe40c292c);
    expect(hash32("foobar")).toBe(0xbf9cf968);
  });
});

describe("ulid", () => {
  it("encodes time in the first 10 characters and sorts by time", () => {
    const rng = new Rng(9);
    const early = ulid(Date.UTC(2026, 9, 13), rng);
    const late = ulid(Date.UTC(2026, 9, 13) + 1, rng);
    expect(early).toMatch(/^[0-9A-HJKMNP-TV-Z]{26}$/);
    expect(early.slice(0, 10) < late.slice(0, 10)).toBe(true);
    expect(ulid(0, rng).slice(0, 10)).toBe("0000000000");
  });

  it("rejects times outside 48 bits", () => {
    expect(() => ulid(-1, new Rng(1))).toThrow(RangeError);
    expect(() => ulid(2 ** 48, new Rng(1))).toThrow(RangeError);
  });

  it("formats UTC timestamps with milliseconds and Z", () => {
    expect(isoTime(Date.UTC(2026, 9, 13, 9, 0, 0, 7))).toBe("2026-10-13T09:00:00.007Z");
  });
});
