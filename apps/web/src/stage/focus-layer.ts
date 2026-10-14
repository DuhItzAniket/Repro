/**
 * The focus highlight (B11; DESIGN.md "Panels": focusing pans and highlights the stage). For the
 * user's focus it outlines the focused files' ring cards, rings their nodes in the dependency web
 * (module and symbol nodes) and brightens the edges that touch them. Every segment carries its
 * node's or edge's appearance time, so scrubbing back hides what has not happened yet.
 *
 * What is focused is resolved once per focus (cards, nodes, a node mask); frames then only write
 * segments, without allocating. Empty while nothing is focused.
 *
 * Two layers share that state (B14): the web's highlight goes under the ring, whose opaque band
 * hides the edges' ends like the web's own, and the card outlines go on top of everything.
 */
import type { CockpitModel } from "../model/cockpit";
import { outerRadius, webRadius } from "./geometry";
import type { PlacedNodes } from "./governor";
import type { StageFrame, StageLayer } from "./layer";
import { type RingModel, rotationAt } from "./ring/layers";
import { ALWAYS, type SegmentWriter, segmentBuffers, segmentWriter } from "./segments";
import { arcSteps, edgeHash, writeArc } from "./web/arcs";

export const MAX_FOCUSED_CARDS = 8;
export const MAX_FOCUSED_NODES = 64;
export const MAX_FOCUSED_EDGES = 400;
const ARC_STEPS = 16;
const NODE_SIDES = 12;
const NODE_RADIUS = 6;
const RING_CAPACITY = MAX_FOCUSED_CARDS * (2 * ARC_STEPS + 2);
const WEB_CAPACITY =
  MAX_FOCUSED_NODES * NODE_SIDES + MAX_FOCUSED_EDGES * arcSteps(Number.POSITIVE_INFINITY);

/** A bright, flare-free highlight segment. */
function line(
  writer: SegmentWriter,
  ax: number,
  ay: number,
  bx: number,
  by: number,
  width: number,
  alpha: number,
  appear: number,
): void {
  writer.push(ax, ay, bx, by, width, 1, 1, 1, alpha, 1, appear, 0);
}

export interface FocusLayers {
  /** Rings on the focused nodes and their brightened edges: add it before the ring. */
  readonly web: StageLayer;
  /** Outlines of the focused files' cards: add it last. */
  readonly ring: StageLayer;
}

export function focusLayers(
  model: CockpitModel,
  layout: PlacedNodes,
  ring: RingModel,
): FocusLayers {
  let resolvedKey = "";
  let resolvedGraph = -1;
  let resolvedRing = -1;
  let cards = new Int32Array(0);
  let nodes = new Int32Array(0);
  let focused = new Uint8Array(0);

  const resolve = (frame: StageFrame): void => {
    const focus = frame.focus;
    const { graph } = model;
    if (
      focus === undefined ||
      (focus.key === resolvedKey &&
        graph.version === resolvedGraph &&
        ring.version === resolvedRing)
    )
      return;
    resolvedKey = focus.key;
    resolvedGraph = graph.version;
    resolvedRing = ring.version;
    const cardList: number[] = [];
    for (const file of focus.files) {
      const card = ring.cardOf.get(file);
      if (card !== undefined && cardList.length < MAX_FOCUSED_CARDS) cardList.push(card);
    }
    cards = Int32Array.from(cardList);
    const nodeList: number[] = [];
    for (let n = 0; n < graph.nodeCount && nodeList.length < MAX_FOCUSED_NODES; n++) {
      if (graph.nodeTypeName(n) === "module" && focus.files.has(graph.files[n] as string))
        nodeList.push(n);
    }
    for (const symbol of focus.symbols) {
      const node = graph.nodeForSymbol(symbol);
      if (node !== undefined && !nodeList.includes(node) && nodeList.length < MAX_FOCUSED_NODES)
        nodeList.push(node);
    }
    nodes = Int32Array.from(nodeList);
    focused = new Uint8Array(graph.nodeCount);
    for (const n of nodeList) focused[n] = 1;
  };

  /** A layer that is empty while nothing is focused and else draws with `draw`. */
  const focusPart = (
    name: string,
    capacity: number,
    draw: (writer: SegmentWriter, frame: StageFrame) => void,
  ): StageLayer => {
    const buffers = segmentBuffers(capacity);
    const writer = segmentWriter(buffers, capacity);
    let empty = false;
    return {
      name,
      primitive: "segments",
      buffers,
      update(frame: StageFrame) {
        if (frame.focus === undefined || frame.focus.key === "") {
          if (!empty) writer.begin();
          empty = true;
          return;
        }
        empty = false;
        ring.sync();
        resolve(frame);
        writer.begin();
        draw(writer, frame);
      },
    };
  };

  const ringPart = focusPart("focus-ring", RING_CAPACITY, (writer, frame) => {
    const { cx, cy, r } = frame.ring;

    // Ring: an outline around each focused file's card, rim to rim.
    const rotation = rotationAt(ring, frame.t, frame.motion, frame.focus);
    const inner = r - 2;
    const outer = outerRadius(frame.ring) + 2;
    for (let c = 0; c < cards.length; c++) {
      const card = cards[c] as number;
      const appear = ring.content.cards[card]?.appear ?? ALWAYS;
      const a0 = (ring.angles.start[card] as number) + rotation;
      const a1 = (ring.angles.end[card] as number) + rotation;
      for (let side = 0; side < 2; side++) {
        const radius = side === 0 ? inner : outer;
        for (let s = 0; s < ARC_STEPS; s++) {
          const u0 = a0 + ((a1 - a0) * s) / ARC_STEPS;
          const u1 = a0 + ((a1 - a0) * (s + 1)) / ARC_STEPS;
          line(
            writer,
            cx + Math.cos(u0) * radius,
            cy + Math.sin(u0) * radius,
            cx + Math.cos(u1) * radius,
            cy + Math.sin(u1) * radius,
            1.5,
            0.95,
            appear,
          );
        }
        const edge = side === 0 ? a0 : a1;
        line(
          writer,
          cx + Math.cos(edge) * inner,
          cy + Math.sin(edge) * inner,
          cx + Math.cos(edge) * outer,
          cy + Math.sin(edge) * outer,
          1.5,
          0.95,
          appear,
        );
      }
    }
  });

  const webPart = focusPart("focus-web", WEB_CAPACITY, (writer, frame) => {
    const { cx, cy } = frame.ring;
    // Web: rings on the focused nodes and the edges that touch them.
    const positions = layout.positions;
    if (positions === null) return;
    const { graph, store } = model;
    const radius = webRadius(frame.ring);
    for (let k = 0; k < nodes.length; k++) {
      const n = nodes[k] as number;
      if (n * 2 + 1 >= positions.length) continue; // newer than the layout
      const x = cx + (positions[n * 2] as number) * radius;
      const y = cy + (positions[n * 2 + 1] as number) * radius;
      const appear = store.time[graph.nodeEvent[n] as number] as number;
      for (let s = 0; s < NODE_SIDES; s++) {
        const u0 = (s / NODE_SIDES) * Math.PI * 2;
        const u1 = ((s + 1) / NODE_SIDES) * Math.PI * 2;
        line(
          writer,
          x + Math.cos(u0) * NODE_RADIUS,
          y + Math.sin(u0) * NODE_RADIUS,
          x + Math.cos(u1) * NODE_RADIUS,
          y + Math.sin(u1) * NODE_RADIUS,
          1.5,
          0.95,
          appear,
        );
      }
    }
    let edges = 0;
    for (let e = 0; e < graph.edgeCount && edges < MAX_FOCUSED_EDGES; e++) {
      const a = graph.edgeSource[e] as number;
      const b = graph.edgeTarget[e] as number;
      if (focused[a] !== 1 && focused[b] !== 1) continue;
      if (Math.max(a, b) * 2 + 1 >= positions.length) continue;
      edges++;
      // The same arc as the web draws for this edge, brighter.
      writeArc(
        writer,
        cx + (positions[a * 2] as number) * radius,
        cy + (positions[a * 2 + 1] as number) * radius,
        cx + (positions[b * 2] as number) * radius,
        cy + (positions[b * 2 + 1] as number) * radius,
        edgeHash(a, b),
        frame.width,
        frame.height,
        1.2,
        0.55,
        store.time[graph.edgeEvent[e] as number] as number,
        0,
      );
    }
  });

  return { web: webPart, ring: ringPart };
}
