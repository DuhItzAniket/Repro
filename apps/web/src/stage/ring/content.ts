/**
 * What the ring shows (B06; DESIGN.md "Ring"): one card per file, built only from what the
 * event stream says about that file. A v1 event never carries file contents, so a card is the
 * file's outline: its path, the modules it imports (`graph.edge`), and its symbols with line
 * numbers (`graph.node`). A small metadata card beside it shows the file name, counts and
 * changes (`symbol.changed`). At 3–4 px the text is texture, but it is honest texture.
 *
 * The content is computed from the whole log, like the web's edges. Each card carries the
 * presentation times at which it appears, joins the blast radius, and is changed, and the
 * shader reveals and highlights it from those. Playback and scrubbing only move uniforms.
 */
import type { CockpitModel } from "../../model/cockpit";

/** Time used for "never" in per-instance times (far beyond any run). */
export const NEVER = 1e9;
/** Most cards on the ring; with fewer files every file gets one. */
export const MAX_CARDS = 160;
const MAX_IMPORTS = 4;
const MAX_SYMBOLS = 4;

export interface RingCard {
  readonly file: string;
  /** Text lines of the content card (inner column). */
  readonly lines: readonly string[];
  /** Text lines of the metadata card (outer column, the ring's "scale labels"). */
  readonly meta: readonly string[];
  /** Relative tangential size. */
  readonly weight: number;
  readonly appear: number;
  readonly blastAt: number;
  readonly changedAt: number;
}

export interface FocusEvent {
  /** Presentation time of the event. */
  readonly time: number;
  /** Index of the card it targets. */
  readonly card: number;
}

export interface RingContent {
  readonly cards: readonly RingCard[];
  /** Events that turn the ring to their file, in time order. */
  readonly focus: readonly FocusEvent[];
  /** Changes whenever any card's text changes (the atlas cache key). */
  readonly key: string;
}

/** File named by an event target: its `file`, or the file part of a pytest node id. */
export function targetFile(
  target: { file?: string; test?: string } | null | undefined,
): string | undefined {
  if (target === null || target === undefined) return undefined;
  if (target.file !== undefined) return target.file;
  const test = target.test;
  if (test === undefined) return undefined;
  const sep = test.indexOf("::");
  return sep < 0 ? test : test.slice(0, sep);
}

const FOCUS_KINDS = new Set([
  "symbol.changed",
  "claim.extracted",
  "diff.behaviour",
  "diff.tests",
  "diff.perf",
  "diff.api",
  "verdict.issued",
  "missing.recorded",
]);

function shortName(module: string): string {
  const parts = module.split(".");
  return parts.length > 2 ? `…${parts.slice(-2).join(".")}` : module;
}

function shortPath(file: string): string {
  const parts = file.split("/");
  return parts.length > 2 ? `…/${parts.slice(-2).join("/")}` : file;
}

export function ringContent(model: CockpitModel, maxCards = MAX_CARDS): RingContent {
  const { graph, store } = model;
  const moduleOf = new Map<string, number>(); // file → module node
  const symbols = new Map<string, number[]>(); // file → non-module nodes
  for (let i = 0; i < graph.nodeCount; i++) {
    const file = graph.files[i] as string;
    if (graph.nodeTypeName(i) === "module") moduleOf.set(file, i);
    else symbols.set(file, [...(symbols.get(file) ?? []), i]);
  }
  const imports = new Map<number, number[]>(); // module node → imported module nodes
  for (let e = 0; e < graph.edgeCount; e++) {
    if (graph.edgeTypeName(e) !== "imports") continue;
    const source = graph.edgeSource[e] as number;
    imports.set(source, [...(imports.get(source) ?? []), graph.edgeTarget[e] as number]);
  }

  // Times per file from the log: blast radius membership, first change, and focus events.
  const blastAt = new Map<string, number>();
  const changedAt = new Map<string, number>();
  const changes = new Map<string, number>();
  const focusRaw: { time: number; file: string }[] = [];
  for (let i = 0; i < store.length; i++) {
    const event = store.event(i);
    if (event === null) continue;
    const time = store.time[i] as number;
    if (event.kind === "blast.computed") {
      for (const symbol of [
        ...event.payload.changed,
        ...event.payload.affected.map((a) => a.symbol_id),
      ]) {
        const node = graph.nodeForSymbol(symbol);
        const file = node === undefined ? undefined : graph.files[node];
        if (file !== undefined && !blastAt.has(file)) blastAt.set(file, time);
      }
    } else if (event.kind === "symbol.changed") {
      const file = event.payload.file;
      if (!changedAt.has(file)) changedAt.set(file, time);
      changes.set(file, (changes.get(file) ?? 0) + 1);
    }
    if (FOCUS_KINDS.has(event.kind)) {
      const file =
        event.kind === "claim.extracted"
          ? targetFile(event.payload.claim.targets[0])
          : targetFile(event.target);
      if (file !== undefined) focusRaw.push({ time, file });
    }
  }

  // Selection: files the run is about first, then the rest in path order; shown in path order.
  const files = [...moduleOf.keys()].sort();
  const important = new Set([
    ...blastAt.keys(),
    ...changedAt.keys(),
    ...focusRaw.map((f) => f.file),
  ]);
  const chosen = new Set(files.filter((f) => important.has(f)).slice(0, maxCards));
  for (const file of files) {
    if (chosen.size >= maxCards) break;
    chosen.add(file);
  }
  const ordered = files.filter((f) => chosen.has(f));

  const cards: RingCard[] = ordered.map((file) => {
    const module = moduleOf.get(file) as number;
    const imported = (imports.get(module) ?? []).map(
      (n) => `import ${shortName(graph.ids[n] as string)}`,
    );
    const own = (symbols.get(file) ?? [])
      .map((n) => {
        const id = graph.ids[n] as string;
        const name = id.slice(id.indexOf(":") + 1, id.lastIndexOf("#"));
        const kind = graph.nodeTypeName(n) === "class" ? "class" : "def";
        return `${kind} ${name.split(".").at(-1)}`;
      })
      .sort();
    const lines = [
      shortPath(file),
      ...imported.slice(0, MAX_IMPORTS),
      ...own.slice(0, MAX_SYMBOLS),
    ];
    const changed = changes.get(file) ?? 0;
    const meta = [
      file.split("/").at(-1) ?? file,
      `${imported.length} imp`,
      `${own.length} sym`,
      changed > 0 ? `±${changed}` : "",
    ];
    return {
      file,
      lines,
      meta,
      weight: 1 + lines.length,
      appear: store.time[graph.nodeEvent[module] as number] as number,
      blastAt: blastAt.get(file) ?? NEVER,
      changedAt: changedAt.get(file) ?? NEVER,
    };
  });

  const index = new Map(ordered.map((file, i) => [file, i]));
  const focus = focusRaw.flatMap(({ time, file }) => {
    const card = index.get(file);
    return card === undefined ? [] : [{ time, card }];
  });
  let key = `${cards.length}`;
  for (const card of cards) key += `|${card.lines.join("\n")}#${card.meta.join("\n")}`;
  return { cards, focus, key };
}
