/**
 * Computes the web layout off the main thread and caches it by graph hash (ARCHITECTURE §13).
 * Layers read `positions` (unit-disc coordinates per graph node, or null while computing) and
 * redraw when `version` changes.
 */
import type { GraphIndex } from "../../model/graph";
import { type LayoutInput, layoutHash, layoutInput } from "./layout-input";

export type LayoutCompute = (input: LayoutInput) => Promise<Float32Array>;

/**
 * Runs the layout on the calling thread (tests, and browsers without module workers). d3-force
 * is loaded on first use, so it ships in the main bundle only as a lazy chunk.
 */
export const computeInline: LayoutCompute = async (input) =>
  (await import("./force")).forceLayout(input);

/** Runs each layout in a module worker (`layout.worker.ts`). */
export function workerCompute(): LayoutCompute {
  let worker: Worker | null = null;
  let next = 0;
  const pending = new Map<number, (positions: Float32Array) => void>();
  return (input) => {
    if (worker === null) {
      worker = new Worker(new URL("./layout.worker.ts", import.meta.url), { type: "module" });
      worker.onmessage = (event: MessageEvent<{ id: number; positions: Float32Array }>) => {
        pending.get(event.data.id)?.(event.data.positions);
        pending.delete(event.data.id);
      };
    }
    const id = next++;
    // The copies are transferred; the caller keeps its own.
    const links = input.links.slice();
    const tests = input.tests.slice();
    worker.postMessage({ id, ids: input.ids, links, containment: input.containment, tests }, [
      links.buffer,
      tests.buffer,
    ]);
    return new Promise((resolve) => pending.set(id, resolve));
  };
}

export class LayoutService {
  private readonly cache = new Map<string, Float32Array>();
  private requested = "";
  private _positions: Float32Array | null = null;
  private _version = 0;

  constructor(
    private readonly graph: GraphIndex,
    private readonly compute: LayoutCompute,
  ) {}

  /** Unit-disc positions per graph node (x, y pairs), or null until the first layout lands. */
  get positions(): Float32Array | null {
    return this._positions;
  }

  /** Bumped whenever `positions` changes. */
  get version(): number {
    return this._version;
  }

  /** Lays out the graph as it is now; resolves when that layout is in place. Cached by hash. */
  async request(): Promise<void> {
    const input = layoutInput(this.graph);
    const hash = layoutHash(input);
    if (hash === this.requested) return;
    this.requested = hash;
    const cached = this.cache.get(hash);
    const positions = cached ?? (await this.compute(input));
    this.cache.set(hash, positions);
    if (this.requested !== hash) return; // a newer graph was requested meanwhile
    this._positions = positions;
    this._version++;
  }
}
