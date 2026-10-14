/**
 * What the ring shows (B06, restyled in B14; DESIGN.md "Ring"): one card per file, built only
 * from what the event stream says about that file. A v1 event never carries file contents, so a
 * card is the file's outline, laid out like the reference's code cards:
 * - a header, `// package / module`;
 * - rows of `line  code`: its functions, classes and tests with their line numbers
 *   (`graph.node`), changed ones in `--flag` (`symbol.changed`), then its imports
 *   (`graph.edge`);
 * - a neighbour fingerprint: a grid of dots, one bucket of the repo's modules per dot, lit where
 *   the file imports or is imported by a module in that bucket;
 * - labels on the outer column: imports, importers, symbols and changes.
 *
 * The content is computed from the whole log, like the web's edges. Each card carries the
 * presentation times at which it appears, joins the blast radius, and is changed, and the
 * shader reveals and highlights it from those. Playback and scrubbing only move uniforms.
 */
import type { CockpitModel } from "../../model/cockpit";
import { type AtlasCard, type CardRow, cardUnits, DOT_COLS } from "./atlas";

/** Time used for "never" in per-instance times (far beyond any run). */
export const NEVER = 1e9;
/** Most cards on the ring; with fewer files every file gets one. */
export const MAX_CARDS = 64;
const MAX_SYMBOL_ROWS = 6;
const MAX_ROWS = 10;
const DOT_ROWS = 4;
/** A file needs this many neighbours for its fingerprint to be drawn. */
const MIN_DOTS = 3;

export interface RingCard extends AtlasCard {
  readonly file: string;
  /** Tangential size in band units (`cardUnits`). */
  readonly units: number;
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

/** `// package / module` from a dotted module name (its last two parts). */
export function cardHeader(module: string): string {
  const parts = module.split(".");
  const name = parts.at(-1) ?? module;
  const pkg = parts.length > 1 ? parts.at(-2) : "";
  return pkg === "" ? `// ${name}` : `// ${pkg} / ${name}`;
}

/** An import as Python would write it: `from a.b import c`, or `import a`. */
function importLine(module: string): string {
  const dot = module.lastIndexOf(".");
  return dot < 0
    ? `import ${module}`
    : `from ${module.slice(0, dot)} import ${module.slice(dot + 1)}`;
}

/** The symbol's name within its module, from an id like `pkg.mod:Class.method#0`. */
function symbolName(id: string): string {
  const colon = id.indexOf(":");
  const hash = id.lastIndexOf("#");
  const qualified = id.slice(colon + 1, hash < 0 ? undefined : hash);
  const sep = qualified.lastIndexOf("::");
  return (sep < 0 ? qualified : qualified.slice(sep + 2)).split(".").at(-1) ?? qualified;
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
  const importers = new Map<number, number>(); // module node → how many modules import it
  const neighbours = new Map<number, Set<number>>(); // module node → modules either way
  const link = (a: number, b: number) => {
    let set = neighbours.get(a);
    if (set === undefined) {
      set = new Set();
      neighbours.set(a, set);
    }
    set.add(b);
  };
  for (let e = 0; e < graph.edgeCount; e++) {
    if (graph.edgeTypeName(e) !== "imports") continue;
    const source = graph.edgeSource[e] as number;
    const target = graph.edgeTarget[e] as number;
    imports.set(source, [...(imports.get(source) ?? []), target]);
    importers.set(target, (importers.get(target) ?? 0) + 1);
    link(source, target);
    link(target, source);
  }

  // Times per file from the log: blast radius membership, first change, and focus events.
  const blastAt = new Map<string, number>();
  const changedAt = new Map<string, number>();
  const changes = new Map<string, number>();
  const changedSymbols = new Set<string>();
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
      changedSymbols.add(event.payload.symbol_id);
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
  const position = new Map<number, number>(); // module node → its index in path order
  files.forEach((file, i) => {
    position.set(moduleOf.get(file) as number, i);
  });
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
    const own = (symbols.get(file) ?? [])
      .map((n) => {
        const id = graph.ids[n] as string;
        const event = store.event(graph.nodeEvent[n] as number);
        const line = event?.kind === "graph.node" ? (event.payload.node.line ?? null) : null;
        const type = graph.nodeTypeName(n);
        const name = type === "test" ? symbolName(id.replace("::", ":")) : symbolName(id);
        const text = type === "class" ? `class ${name}:` : `def ${name}()`;
        return {
          line: line ?? 0,
          num: line === null ? "" : `${line}`,
          text,
          flag: changedSymbols.has(id),
        };
      })
      .sort((a, b) => a.line - b.line || a.text.localeCompare(b.text));
    const imported = (imports.get(module) ?? []).map((n) => graph.ids[n] as string).sort();
    const rows: CardRow[] = [
      ...own.slice(0, MAX_SYMBOL_ROWS).map(({ num, text, flag }) => ({ num, text, flag })),
      ...imported.map((m) => ({ num: "", text: importLine(m), flag: false })),
    ].slice(0, MAX_ROWS);
    const linked = neighbours.get(module) ?? new Set<number>();
    const buckets = DOT_COLS * DOT_ROWS;
    const dots =
      linked.size >= MIN_DOTS
        ? [...new Set([...linked].map((n) => (position.get(n) ?? 0) % buckets))].sort(
            (a, b) => a - b,
          )
        : [];
    const changed = changes.get(file) ?? 0;
    const meta = [
      `${imported.length} imp`,
      `${importers.get(module) ?? 0} in`,
      own.length > 0 ? `${own.length} sym` : "",
      changed > 0 ? `±${changed}` : "",
    ];
    const atlas: AtlasCard = {
      header: cardHeader(graph.ids[module] as string),
      rows,
      dots,
      dotRows: dots.length > 0 ? DOT_ROWS : 0,
      meta,
    };
    return {
      file,
      ...atlas,
      units: cardUnits(atlas),
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
  for (const card of cards) {
    key += `|${card.header}\n${card.rows.map((r) => `${r.num} ${r.text}${r.flag ? "!" : ""}`).join("\n")}#${card.dots.join(",")}#${card.meta.join("\n")}`;
  }
  return { cards, focus, key };
}
