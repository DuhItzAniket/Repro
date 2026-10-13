/**
 * The synthetic repository around the story: filler modules, an import graph with hubs and
 * package locality, extra blast-radius symbols and extra selected tests. Profiles set the sizes.
 */
import type { Rng } from "./rng";
import {
  CHANGES,
  type ModuleSpec,
  moduleFile,
  STORY_CALLS,
  STORY_IMPORTS,
  STORY_MODULES,
  STORY_TESTS,
  type SymbolSpec,
  storyCovers,
  type TestSpec,
} from "./story";

const SUBPACKAGES: Record<string, readonly string[]> = {
  locales: [
    "en",
    "de",
    "fr",
    "es",
    "it",
    "pt",
    "nl",
    "sv",
    "da",
    "fi",
    "nb",
    "pl",
    "cs",
    "sk",
    "hu",
    "ro",
    "bg",
    "el",
    "tr",
    "ru",
    "uk",
    "ar",
    "he",
    "fa",
    "hi",
    "bn",
    "ja",
    "zh",
    "ko",
    "th",
    "vi",
    "id",
    "ms",
    "ca",
    "eu",
    "gl",
    "hr",
    "sl",
    "sr",
    "lt",
    "lv",
    "et",
  ],
  calendars: [
    "gregorian",
    "julian",
    "hebrew",
    "islamic",
    "persian",
    "ethiopic",
    "coptic",
    "buddhist",
    "japanese",
    "chinese",
    "indian",
    "proleptic",
  ],
  tz: ["rules", "offsets", "windows", "posix", "tzfile", "leap", "abbrev", "links"],
  io: ["json", "csv", "ical", "rfc2822", "rfc3339", "msgpack", "pickle_compat"],
  ranges: ["interval", "span", "overlap", "gaps", "merge", "slicer"],
  holidays: ["us", "gb", "de", "fr", "in", "jp", "br", "ca", "au", "mx", "za", "kr", "it", "es"],
  business: ["days", "hours", "calendar", "shift", "rollover", "settlement"],
  astro: ["sun", "moon", "equinox", "twilight", "julian_day", "sidereal"],
  units: ["duration", "period", "ticks", "epoch", "leap_seconds"],
  formats: ["strftime", "strptime", "patterns", "tokens", "ordinal", "plural"],
  contrib: ["dataframes", "arrays", "orm", "validators", "serializers"],
  schedules: ["cron", "rrule_text", "backoff", "jitter", "window"],
};

const VERBS = [
  "parse",
  "format",
  "to",
  "from",
  "normalize",
  "resolve",
  "shift",
  "round",
  "split",
  "merge",
];
const NOUNS = [
  "date",
  "time",
  "offset",
  "span",
  "week",
  "month",
  "zone",
  "token",
  "rule",
  "period",
];

/** Modules that many others import (preferential-attachment seeds). */
const HUBS: Record<string, number> = {
  "timekeeper.core": 40,
  "timekeeper._util": 30,
  "timekeeper.compat": 24,
  "timekeeper.parse": 14,
  "timekeeper.fmt": 10,
  "timekeeper.tz": 10,
};

export interface FillerSymbol extends SymbolSpec {
  /** The story symbol it calls (its route into the blast radius). */
  calls: SymbolSpec;
  distance: number;
}

interface FillerTest {
  spec: TestSpec;
  covers: readonly SymbolSpec[];
}

export type Edge = readonly [source: string, target: string];

export interface Repo {
  modules: readonly ModuleSpec[];
  fillerSymbols: readonly FillerSymbol[];
  /** Selected tests in collection order (by file, then line). */
  tests: readonly TestSpec[];
  /** Symbols each selected test reaches (the selection map). */
  covers: ReadonlyMap<TestSpec, readonly SymbolSpec[]>;
  /** Module imports (static, build stage). */
  imports: readonly Edge[];
  /** Test → symbol coverage and symbol → symbol calls (observed, run stage). */
  coverEdges: readonly Edge[];
  callEdges: readonly Edge[];
}

export interface RepoSize {
  /** Python modules in total (story included). */
  files: number;
  /** Graph edges in total: imports fill whatever coverage and calls leave. */
  edges: number;
  /** Blast-radius symbols outside the story. */
  fillerSymbols: number;
  /** Selected tests outside the story (all pass on every side). */
  fillerTests: number;
  /** Own duration range of each filler test, in ms. */
  fillerTestMs: readonly [number, number];
}

function fillerModules(count: number, rng: Rng): ModuleSpec[] {
  const out: ModuleSpec[] = [];
  const used = new Set(STORY_MODULES.map((m) => m.name));
  const subpackages = Object.keys(SUBPACKAGES);
  const add = (spec: ModuleSpec): void => {
    if (out.length < count && !used.has(spec.name)) {
      used.add(spec.name);
      out.push(spec);
    }
  };
  // Package __init__ modules first, then leaves (about one test module per two leaves).
  for (const sub of subpackages) {
    const name = `timekeeper.${sub}`;
    add({ name, file: moduleFile(name, true), test: false });
  }
  for (let round = 0; out.length < count; round++) {
    for (const sub of rng.shuffled(subpackages)) {
      for (const leaf of SUBPACKAGES[sub] ?? []) {
        const base = round === 0 ? leaf : `${leaf}_${round + 1}`;
        if (rng.chance(0.65)) {
          const name = `timekeeper.${sub}.${base}`;
          add({ name, file: moduleFile(name), test: false });
        } else {
          const name = `tests.${sub}.test_${base}`;
          add({ name, file: moduleFile(name), test: true });
        }
      }
    }
  }
  return out;
}

/** Weighted sampling with weights that grow as nodes are picked (preferential attachment). */
class Popularity {
  private readonly weights: number[];
  private total: number;

  constructor(
    private readonly names: readonly string[],
    initial: (name: string) => number,
  ) {
    this.weights = names.map(initial);
    this.total = this.weights.reduce((sum, w) => sum + w, 0);
  }

  pick(rng: Rng, accept: (name: string) => boolean): string | undefined {
    for (let attempt = 0; attempt < 32; attempt++) {
      let target = rng.float() * this.total;
      for (let i = 0; i < this.names.length; i++) {
        target -= this.weights[i] ?? 0;
        if (target < 0) {
          const name = this.names[i] as string;
          if (!accept(name)) break;
          this.weights[i] = (this.weights[i] ?? 0) + 1;
          this.total += 1;
          return name;
        }
      }
    }
    return undefined;
  }
}

function packageOf(name: string): string {
  const parts = name.split(".");
  return parts.length > 2 ? parts.slice(0, 3).join(".") : parts.join(".");
}

export function buildRepo(size: RepoSize, rng: Rng): Repo {
  const filler = fillerModules(size.files - STORY_MODULES.length, rng.fork("modules"));
  const modules = [...STORY_MODULES, ...filler];
  if (modules.length !== size.files) {
    throw new Error(`could not name ${size.files} modules (got ${modules.length})`);
  }

  // Blast radius outside the story: filler functions that call a changed or affected function.
  const blastRng = rng.fork("blast");
  const packages = filler.filter((m) => !m.test && !m.file.endsWith("__init__.py"));
  const changedTargets = CHANGES.map((c) => c.symbol).filter((s) => s.name !== "<module>");
  const fillerSymbols: FillerSymbol[] = [];
  for (const module of blastRng.shuffled(packages).slice(0, size.fillerSymbols)) {
    const name = `${blastRng.pick(VERBS)}_${blastRng.pick(NOUNS)}`;
    const calls = blastRng.pick(changedTargets);
    fillerSymbols.push({
      id: `${module.name}:${name}#0`,
      type: "function",
      module: module.name,
      file: module.file,
      name,
      line: blastRng.int(8, 240),
      calls,
      distance: 1,
    });
  }
  if (fillerSymbols.length !== size.fillerSymbols) {
    throw new Error(`not enough filler modules for ${size.fillerSymbols} blast-radius symbols`);
  }

  // Extra selected tests: filler test functions covering one or two filler blast symbols.
  const testRng = rng.fork("tests");
  const testModules = filler.filter((m) => m.test);
  const fillerTests: FillerTest[] = [];
  const usedIds = new Set<string>();
  for (let i = 0; fillerTests.length < size.fillerTests; i++) {
    if (testModules.length === 0 || fillerSymbols.length === 0) {
      throw new Error("profile asks for filler tests but has no filler test modules or symbols");
    }
    const module = testModules[i % testModules.length] as ModuleSpec;
    const first = testRng.pick(fillerSymbols);
    const covers: SymbolSpec[] = [first];
    if (testRng.chance(0.4)) {
      const second = testRng.pick(fillerSymbols);
      if (second !== first) covers.push(second);
    }
    const name = `test_${first.name}_${Math.floor(i / testModules.length) + 1}`;
    const id = `${module.file}::${name}`;
    if (usedIds.has(id)) continue;
    usedIds.add(id);
    fillerTests.push({
      covers,
      spec: {
        id,
        module: module.name,
        file: module.file,
        name,
        line: testRng.int(5, 400),
        reasons: ["blast_radius"],
        outcomes: { base: "passed", repeat: "passed", head: "passed" },
        cls: "P2P",
        ms: testRng.int(size.fillerTestMs[0], size.fillerTestMs[1]),
        observations: [],
      },
    });
  }

  // pytest's collection order: by file, then by definition order within the file.
  const tests = [...STORY_TESTS, ...fillerTests.map((t) => t.spec)].sort((a, b) =>
    a.file < b.file ? -1 : a.file > b.file ? 1 : a.line - b.line,
  );
  const covers = new Map<TestSpec, readonly SymbolSpec[]>();
  for (const t of STORY_TESTS) covers.set(t, storyCovers(t));
  for (const t of fillerTests) covers.set(t.spec, t.covers);
  const coverEdges: Edge[] = tests.flatMap((t) =>
    (covers.get(t) ?? []).map((s) => [t.id, s.id] as const),
  );
  const callEdges: Edge[] = [
    ...STORY_CALLS.map(([from, to]) => [from.id, to.id] as const),
    ...fillerSymbols.map((s) => [s.id, s.calls.id] as const),
  ];
  const importTarget = size.edges - coverEdges.length - callEdges.length;

  // Imports: the story's, then the ones the blast radius and tests imply, then a random fill
  // with package locality and hubs until the profile's total is reached.
  const edges = new Set<string>();
  const imports: Edge[] = [];
  const add = (from: string, to: string): boolean => {
    const key = `${from}>${to}`;
    if (from === to || edges.has(key)) return false;
    edges.add(key);
    imports.push([from, to]);
    return true;
  };
  for (const [from, to] of STORY_IMPORTS) add(from, to);
  for (const symbol of fillerSymbols) add(symbol.module, symbol.calls.module);
  for (const t of fillerTests) for (const symbol of t.covers) add(t.spec.module, symbol.module);
  if (imports.length > importTarget) {
    throw new Error(`profile allows ${importTarget} imports but the story needs ${imports.length}`);
  }

  const importRng = rng.fork("imports");
  const importable = modules.filter((m) => !m.test).map((m) => m.name);
  const popularity = new Popularity(importable, (name) => HUBS[name] ?? 1);
  const byPackage = new Map<string, string[]>();
  for (const name of importable) {
    const key = packageOf(name);
    byPackage.set(key, [...(byPackage.get(key) ?? []), name]);
  }
  let stalls = 0;
  while (imports.length < importTarget) {
    const from = importRng.pick(modules);
    const local = byPackage.get(packageOf(from.name.replace(/^tests\./, "timekeeper.")));
    const to =
      local !== undefined && local.length > 1 && importRng.chance(0.45)
        ? importRng.pick(local)
        : popularity.pick(importRng, (name) => name !== from.name);
    if (to !== undefined && add(from.name, to)) {
      stalls = 0;
    } else if (++stalls > 10_000) {
      throw new Error(`import graph saturated at ${imports.length} edges`);
    }
  }

  return { modules, fillerSymbols, tests, covers, imports, coverEdges, callEdges };
}
