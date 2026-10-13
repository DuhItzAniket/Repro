/**
 * Seeded pseudo-random numbers for synthetic runs.
 *
 * The same seed must give a byte-identical log (B01), so nothing here touches `Math.random`,
 * the clock, or transcendental functions (`Math.log`, `Math.sin`, …). Those may round differently
 * across JavaScript engines. Only integer operations and IEEE-754 `+ - * /` are used.
 *
 * Generator: sfc32 (the 32-bit Small Fast Chaotic generator from PractRand), with the four state
 * words seeded through splitmix32. Each concern of the generator draws from its own named stream
 * (`fork`). So adding a draw in one part of the generator does not reshuffle the others.
 */

const TWO_POW_32 = 4294967296;

/** FNV-1a over UTF-16 code units: a stable 32-bit hash for stream names and ids. */
export function hash32(text: string): number {
  let hash = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193);
  }
  return hash >>> 0;
}

function splitmix32(state: number): [next: number, output: number] {
  const next = (state + 0x9e3779b9) | 0;
  let z = next;
  z = Math.imul(z ^ (z >>> 16), 0x85ebca6b);
  z = Math.imul(z ^ (z >>> 13), 0xc2b2ae35);
  z ^= z >>> 16;
  return [next, z >>> 0];
}

export class Rng {
  readonly seed: number;
  private a: number;
  private b: number;
  private c: number;
  private d: number;

  constructor(seed: number) {
    if (!Number.isInteger(seed) || seed < 0 || seed >= TWO_POW_32) {
      throw new RangeError(`seed must be a uint32, got ${seed}`);
    }
    this.seed = seed;
    let state = seed | 0;
    const words: number[] = [];
    for (let i = 0; i < 4; i++) {
      const [next, output] = splitmix32(state);
      state = next;
      words.push(output);
    }
    [this.a, this.b, this.c, this.d] = words as [number, number, number, number];
    for (let i = 0; i < 12; i++) this.next(); // discard the warm-up outputs
  }

  /** An independent stream derived from this generator's seed and a name (not its state). */
  fork(name: string): Rng {
    return new Rng((Math.imul(this.seed ^ hash32(name), 0x9e3779b1) ^ hash32(`/${name}`)) >>> 0);
  }

  /** Next uint32. */
  next(): number {
    const t = (((this.a + this.b) | 0) + this.d) | 0;
    this.d = (this.d + 1) | 0;
    this.a = this.b ^ (this.b >>> 9);
    this.b = (this.c + (this.c << 3)) | 0;
    this.c = (this.c << 21) | (this.c >>> 11);
    this.c = (this.c + t) | 0;
    return t >>> 0;
  }

  /** Uniform in [0, 1). */
  float(): number {
    return this.next() / TWO_POW_32;
  }

  /** Uniform integer in [lo, hi] (inclusive). */
  int(lo: number, hi: number): number {
    if (hi < lo) throw new RangeError(`empty range [${lo}, ${hi}]`);
    return lo + Math.floor(this.float() * (hi - lo + 1));
  }

  /** Integer in [lo, hi], skewed towards lo (density falls off like 1 − √x). */
  skewed(lo: number, hi: number): number {
    const u = this.float();
    return lo + Math.floor(u * u * (hi - lo + 1));
  }

  chance(probability: number): boolean {
    return this.float() < probability;
  }

  pick<T>(items: readonly T[]): T {
    if (items.length === 0) throw new RangeError("pick from an empty list");
    return items[Math.floor(this.float() * items.length)] as T;
  }

  /** Fisher–Yates on a copy. */
  shuffled<T>(items: readonly T[]): T[] {
    const out = [...items];
    for (let i = out.length - 1; i > 0; i--) {
      const j = Math.floor(this.float() * (i + 1));
      [out[i], out[j]] = [out[j] as T, out[i] as T];
    }
    return out;
  }

  /** Lowercase hex string of `length` digits. */
  hex(length: number): string {
    let out = "";
    while (out.length < length) out += this.next().toString(16).padStart(8, "0");
    return out.slice(0, length);
  }
}
