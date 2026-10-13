/**
 * CPU-side instance data for one stage layer: one Float32Array per attribute, preallocated and
 * reused across frames. A layer's *render model* is exactly what it uploads to the GPU, so
 * render correctness is tested without a GPU by hashing these arrays (ADR-0008).
 */

export interface AttributeSpec {
  readonly name: string;
  /** Floats per instance (1–4). */
  readonly size: number;
}

export class InstanceBuffers {
  readonly arrays: Record<string, Float32Array>;
  private _capacity: number;
  /** Instances written this frame. */
  count = 0;
  /** Bumped whenever the contents change; the host re-uploads only then. */
  version = 0;
  /** Bumped when arrays are reallocated (GPU attributes must be recreated). */
  generation = 0;

  constructor(
    readonly specs: readonly AttributeSpec[],
    capacity: number,
  ) {
    this._capacity = Math.max(1, capacity);
    this.arrays = {};
    for (const spec of specs) this.arrays[spec.name] = new Float32Array(this._capacity * spec.size);
  }

  get capacity(): number {
    return this._capacity;
  }

  array(name: string): Float32Array {
    const array = this.arrays[name];
    if (array === undefined) throw new Error(`no instance attribute "${name}"`);
    return array;
  }

  /** Grows (never shrinks) to hold `n` instances. Only allocates when `n` exceeds the capacity. */
  reserve(n: number): void {
    if (n <= this._capacity) return;
    let capacity = this._capacity;
    while (capacity < n) capacity *= 2;
    for (const spec of this.specs) {
      const next = new Float32Array(capacity * spec.size);
      next.set(this.array(spec.name));
      this.arrays[spec.name] = next;
    }
    this._capacity = capacity;
    this.generation++;
  }
}

export interface RenderModel {
  readonly layer: string;
  readonly buffers: InstanceBuffers;
}

/** Quantisation for hashing: 1/256 px for positions, which is far below anything visible. */
const QUANTUM = 256;

/**
 * A stable 64-bit hex digest of render models: layer names, instance counts, and every
 * attribute value of every instance, quantised to 1/256 so that last-bit differences in
 * floating-point maths across JavaScript engines cannot change it.
 */
export function hashRenderModels(models: readonly RenderModel[]): string {
  let a = 0x811c9dc5;
  let b = 0x01000193 ^ 0x5bd1e995;
  const mix = (value: number): void => {
    for (let shift = 0; shift < 32; shift += 8) {
      const byte = (value >>> shift) & 0xff;
      a = Math.imul(a ^ byte, 0x01000193);
      b = Math.imul(b ^ byte, 0x5bd1e995) ^ (b >>> 15);
    }
  };
  for (const { layer, buffers } of models) {
    for (let i = 0; i < layer.length; i++) mix(layer.charCodeAt(i));
    mix(buffers.count);
    for (const spec of buffers.specs) {
      const array = buffers.array(spec.name);
      const used = buffers.count * spec.size;
      for (let i = 0; i < used; i++) mix(Math.round((array[i] as number) * QUANTUM) | 0);
    }
  }
  const hex = (x: number) => (x >>> 0).toString(16).padStart(8, "0");
  return hex(a) + hex(b);
}
