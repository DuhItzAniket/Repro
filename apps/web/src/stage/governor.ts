/**
 * The flash governor (ADR-0011; WCAG 2.2 SC 2.3.1). Streaks, bundles and recency flares are
 * flashes: they brighten and then fade. The governor caps the bright area that may *rise* within
 * any 333 ms of wall-clock time at `FLASH_BUDGET`, half of WCAG's 87,296 CSS px² flashing area.
 * Over the cap:
 * - a bundle is dropped, and at most one bundle per graph edge rises per window (aggregation);
 * - a streak is not drawn (its intensity is reduced to zero);
 * - an edge or marker appears without its flare (a rise that does not fall is not a flash).
 *
 * Why this bounds flashing: if at most B px² can rise in any 333 ms, at most 3B can rise in any
 * second, so the area that flashes more than three times a second is at most 3B/4 < B. Areas are
 * upper bounds from each element's own geometry (`streakArea`, `bundleArea`, `arcArea`), and
 * the budget applies to the whole stage, not per 10° field, so the estimate errs on the safe side.
 * An edge counts only its pieces on the stage (most of the web is off-screen since B14), and a
 * bundle its longest possible reach.
 *
 * Decisions are made greedily in log order and depend only on the events up to each onset, the
 * replay speed and the stage geometry. They are therefore a pure function of (events, speed,
 * geometry): the same when playing or scrubbing, and extended, never revised, as events arrive.
 */
import { hash32 } from "@repro/synth";
import type { CockpitModel } from "../model/cockpit";
import { webRadius } from "./geometry";
import type { StageFrame } from "./layer";
import { streakArea } from "./streams/layers";
import { streams } from "./streams/style";
import { arcArea, edgeHash } from "./web/arcs";
import { BUNDLE_REACH, bundleArea, EDGE_STYLE, MARKER_AREA } from "./web/layers";

/** What the governor needs from the web layout (a `LayoutService`, or a stub in tests). */
export interface PlacedNodes {
  /** Node positions (x, y per node, unit-disc coordinates), or null before the first layout. */
  readonly positions: Float32Array | null;
  readonly version: number;
}

/** WCAG 2.2 Understanding SC 2.3.1: 341 × 256 CSS px of concurrent flashing area. */
export const WCAG_FLASH_AREA = 87_296;
/** The governor's cap: half the WCAG area, a margin for estimation error. */
export const FLASH_BUDGET = WCAG_FLASH_AREA / 2;
/** The window, in wall-clock ms: a third of a second, for at most three flashes a second. */
export const FLASH_WINDOW_MS = 333;

export type OnsetKind = "streak" | "bundle" | "edge" | "marker";

/** Admitted onsets, in log order (for tests and diagnostics). */
export interface OnsetLog {
  readonly time: number[];
  readonly area: number[];
  readonly kind: OnsetKind[];
}

export class FlashGovernor {
  /** Bumped whenever decisions change, so static layers know to rewrite. */
  version = 0;
  private streakOk = new Uint8Array(0);
  private bundleOk = new Uint8Array(0);
  private markerOk = new Uint8Array(0);
  private edgeOk = new Uint8Array(0);
  private processed = 0;
  private nextEdge = 0;
  private window = FLASH_WINDOW_MS;
  /** The sliding window of admitted onsets: times, areas, its first live entry and their sum. */
  private readonly times: number[] = [];
  private readonly areas: number[] = [];
  private head = 0;
  private sum = 0;
  /** Graph edge (from × 2^20 + to) → time of its last admitted bundle. */
  private readonly lastBundle = new Map<number, number>();
  private log: OnsetLog = { time: [], area: [], kind: [] };
  private speed = Number.NaN;
  private ring = { cx: Number.NaN, cy: Number.NaN, r: Number.NaN };
  private width = Number.NaN;
  private height = Number.NaN;
  private layoutVersion = -1;

  constructor(
    private readonly model: CockpitModel,
    private readonly layout: PlacedNodes,
    /**
     * The cap per window. An infinite budget turns the governor off entirely (no cap and no
     * aggregation): the stress bench and the capacity tests measure the layers at full load.
     */
    private readonly budget = FLASH_BUDGET,
  ) {}

  /** Brings decisions up to date for this frame. Cheap (and allocation-free) when unchanged. */
  prepare(frame: StageFrame): void {
    const { ring } = frame;
    const { speed } = frame.motion;
    if (
      speed !== this.speed ||
      ring.cx !== this.ring.cx ||
      ring.cy !== this.ring.cy ||
      ring.r !== this.ring.r ||
      frame.width !== this.width ||
      frame.height !== this.height ||
      this.layout.version !== this.layoutVersion
    ) {
      this.speed = speed;
      this.ring = { cx: ring.cx, cy: ring.cy, r: ring.r };
      this.width = frame.width;
      this.height = frame.height;
      this.layoutVersion = this.layout.version;
      this.reset();
    }
    if (this.processed < this.model.store.length) this.extend();
  }

  /** Whether the streak of the event at store index `i` is drawn. */
  streak(i: number): boolean {
    return this.streakOk[i] === 1;
  }

  /** Whether the bundle of the event at store index `i` is drawn. */
  bundle(i: number): boolean {
    return this.bundleOk[i] === 1;
  }

  /** Whether graph edge `e` flares when it appears. */
  edgeFlare(e: number): boolean {
    return this.edgeOk[e] === 1;
  }

  /** Whether the blast markers of the `blast.computed` event at store index `i` flare. */
  markerFlare(i: number): boolean {
    return this.markerOk[i] === 1;
  }

  /** Admitted onsets so far (for tests). */
  get onsets(): OnsetLog {
    return this.log;
  }

  private reset(): void {
    this.processed = 0;
    this.nextEdge = 0;
    this.window = FLASH_WINDOW_MS * this.speed;
    this.times.length = 0;
    this.areas.length = 0;
    this.head = 0;
    this.sum = 0;
    this.lastBundle.clear();
    this.log = { time: [], area: [], kind: [] };
    this.streakOk = new Uint8Array(0);
    this.bundleOk = new Uint8Array(0);
    this.markerOk = new Uint8Array(0);
    this.edgeOk = new Uint8Array(0);
  }

  /** Admits an onset of `area` at time `t` if the window has room; returns whether it did. */
  private admit(t: number, area: number, kind: OnsetKind): boolean {
    while (this.head < this.times.length && (this.times[this.head] as number) <= t - this.window) {
      this.sum -= this.areas[this.head] as number;
      this.head++;
    }
    if (this.head > 4096 && this.head * 2 > this.times.length) {
      this.times.splice(0, this.head);
      this.areas.splice(0, this.head);
      this.head = 0;
    }
    if (this.sum + area > this.budget) return false;
    this.times.push(t);
    this.areas.push(area);
    this.sum += area;
    this.log.time.push(t);
    this.log.area.push(area);
    this.log.kind.push(kind);
    return true;
  }

  private extend(): void {
    const { store, graph } = this.model;
    const positions = this.layout.positions;
    const radius = webRadius(this.ring);
    const { cx, cy } = this.ring;
    const reach = BUNDLE_REACH * this.height;
    const n = store.length;
    this.streakOk = grow(this.streakOk, n);
    this.bundleOk = grow(this.bundleOk, n);
    this.markerOk = grow(this.markerOk, n);
    this.edgeOk = grow(this.edgeOk, graph.edgeCount);
    const placed = (a: number): boolean => positions !== null && a * 2 + 1 < positions.length;
    /** On-stage area of the arc between two placed graph nodes. */
    const arcOf = (a: number, b: number, width: number): number => {
      const p = positions as Float32Array;
      return arcArea(
        cx + (p[a * 2] as number) * radius,
        cy + (p[a * 2 + 1] as number) * radius,
        cx + (p[b * 2] as number) * radius,
        cy + (p[b * 2 + 1] as number) * radius,
        edgeHash(a, b),
        this.width,
        this.height,
        width,
      );
    };
    for (let i = this.processed; i < n; i++) {
      const event = store.event(i);
      if (event === null) continue;
      const t = store.time[i] as number;
      if (event.kind === "graph.edge") {
        while (this.nextEdge < graph.edgeCount && (graph.edgeEvent[this.nextEdge] as number) < i)
          this.nextEdge++;
        const e = this.nextEdge;
        if (e < graph.edgeCount && graph.edgeEvent[e] === i) {
          const s = graph.edgeSource[e] as number;
          const target = graph.edgeTarget[e] as number;
          if (placed(s) && placed(target)) {
            const area = arcOf(s, target, EDGE_STYLE[graph.edgeTypeName(e)].width);
            // An edge entirely off the stage draws nothing and cannot flash.
            if (area === 0 || this.admit(t, area, "edge")) this.edgeOk[e] = 1;
          }
        }
        continue;
      }
      if (event.kind === "blast.computed") {
        let markers = 0;
        for (const s of [
          ...event.payload.affected.map((a) => a.symbol_id),
          ...event.payload.changed,
        ]) {
          const node = graph.nodeForSymbol(s);
          if (node !== undefined && placed(node)) markers++;
        }
        if (this.admit(t, markers * MARKER_AREA, "marker")) this.markerOk[i] = 1;
        continue;
      }
      if (event.kind === "trace.sample" || event.kind === "diff.behaviour") {
        const test = event.target?.test;
        const from = test === undefined ? undefined : graph.byId.get(test);
        const to = graph.nodeForSymbol(event.payload.symbol_id);
        if (from !== undefined && to !== undefined && placed(from) && placed(to)) {
          // One bundle per edge per window: a later one on the same edge is aggregated into it.
          const key = from * 1_048_576 + to;
          const last = this.lastBundle.get(key);
          const aggregated =
            Number.isFinite(this.budget) && last !== undefined && t - last < this.window;
          if (!aggregated && this.admit(t, bundleArea(reach, hash32(event.id)), "bundle")) {
            this.bundleOk[i] = 1;
            this.lastBundle.set(key, t);
          }
        }
      }
      if (streams(event) && this.admit(t, streakArea(event), "streak")) this.streakOk[i] = 1;
    }
    this.processed = n;
    this.version++;
  }
}

function grow(array: Uint8Array<ArrayBuffer>, need: number): Uint8Array<ArrayBuffer> {
  if (need <= array.length) return array;
  const next = new Uint8Array(Math.max(need, array.length * 2));
  next.set(array);
  return next;
}
