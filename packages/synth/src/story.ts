/**
 * The scripted pull request behind every synthetic run: a fictional library, four claims, the
 * changes, the selected tests and what each check finds. Profiles scale the repository and the
 * test suite around this story, but the story itself is fixed, so every fixture tells the same
 * coherent story. Everything here is invented and is labelled `synthetic/` in the run.
 */
import type {
  AgentRole,
  Claim,
  ClaimKind,
  OutcomeClass,
  SymbolId,
  TestOutcome,
  VerdictValue,
} from "@repro/events";

export const REPO_NAME = "synthetic/timekeeper";
export const PR_TITLE = "Normalise timezone handling and speed up recurrence expansion";
export const PR_NUMBER = 128;
export const BASE_REF = "main";
export const HEAD_REF = "agent/tz-normalise";
export const PYTHON_VERSION = "3.13.13";
export const PLATFORM = "linux/amd64";
export const REPRO_VERSION = "0.2.0";
export const PRODUCER = `repro/${REPRO_VERSION}+synthetic`;

// ---------------------------------------------------------------------------------------------
// Modules

export interface ModuleSpec {
  /** Dotted module name. */
  name: string;
  /** Repository-relative path. */
  file: string;
  test: boolean;
}

export function moduleFile(name: string, isPackage = false): string {
  const path = name.split(".").join("/");
  return isPackage ? `${path}/__init__.py` : `${path}.py`;
}

const pkg = (name: string): ModuleSpec => ({ name, file: moduleFile(name, true), test: false });
const mod = (name: string): ModuleSpec => ({ name, file: moduleFile(name), test: false });
const testMod = (name: string): ModuleSpec => ({ name, file: moduleFile(name), test: true });

export const STORY_MODULES: readonly ModuleSpec[] = [
  pkg("timekeeper"),
  mod("timekeeper.core"),
  mod("timekeeper._util"),
  mod("timekeeper.compat"),
  mod("timekeeper.parse"),
  mod("timekeeper.fmt"),
  mod("timekeeper.recur"),
  mod("timekeeper.humanize"),
  mod("timekeeper.cli"),
  pkg("timekeeper.tz"),
  mod("timekeeper.tz.fold"),
  mod("timekeeper.tz.zones"),
  pkg("timekeeper.calendars"),
  mod("timekeeper.calendars.iso"),
  testMod("tests.test_parse"),
  testMod("tests.test_fmt"),
  testMod("tests.test_recur"),
  testMod("tests.test_dst"),
  testMod("tests.test_tz"),
  testMod("tests.test_humanize"),
  testMod("tests.test_cli"),
  testMod("tests.test_calendars"),
];

/** Imports the story needs; the profile fills the rest of the import graph around them. */
export const STORY_IMPORTS: readonly (readonly [string, string])[] = [
  ["timekeeper", "timekeeper.core"],
  ["timekeeper", "timekeeper.parse"],
  ["timekeeper", "timekeeper.fmt"],
  ["timekeeper.core", "timekeeper.compat"],
  ["timekeeper.parse", "timekeeper._util"],
  ["timekeeper.parse", "timekeeper.compat"],
  ["timekeeper.parse", "timekeeper.tz"],
  ["timekeeper.fmt", "timekeeper._util"],
  ["timekeeper.recur", "timekeeper.core"],
  ["timekeeper.recur", "timekeeper._util"],
  ["timekeeper.humanize", "timekeeper.fmt"],
  ["timekeeper.humanize", "timekeeper.core"],
  ["timekeeper.cli", "timekeeper.parse"],
  ["timekeeper.cli", "timekeeper.fmt"],
  ["timekeeper.cli", "timekeeper.humanize"],
  ["timekeeper.tz", "timekeeper.tz.zones"],
  ["timekeeper.tz", "timekeeper.tz.fold"],
  ["timekeeper.tz.fold", "timekeeper.tz.zones"],
  ["timekeeper.tz.fold", "timekeeper._util"],
  ["timekeeper.calendars.iso", "timekeeper.parse"],
  ["timekeeper.calendars.iso", "timekeeper.core"],
  ["tests.test_parse", "timekeeper.parse"],
  ["tests.test_fmt", "timekeeper.fmt"],
  ["tests.test_recur", "timekeeper.recur"],
  ["tests.test_dst", "timekeeper.parse"],
  ["tests.test_dst", "timekeeper.tz.fold"],
  ["tests.test_tz", "timekeeper.tz.zones"],
  ["tests.test_tz", "timekeeper.tz.fold"],
  ["tests.test_tz", "timekeeper.parse"],
  ["tests.test_humanize", "timekeeper.humanize"],
  ["tests.test_cli", "timekeeper.cli"],
  ["tests.test_calendars", "timekeeper.calendars.iso"],
];

// ---------------------------------------------------------------------------------------------
// Symbols

export type SymbolType = "class" | "function" | "method";

export interface SymbolSpec {
  id: SymbolId;
  type: SymbolType;
  module: string;
  file: string;
  /** Qualified name within the module. */
  name: string;
  line: number;
}

function sym(module: string, name: string, type: SymbolType, line: number): SymbolSpec {
  const spec = STORY_MODULES.find((m) => m.name === module);
  if (spec === undefined) throw new Error(`unknown story module ${module}`);
  return { id: `${module}:${name}#0`, type, module, file: spec.file, name, line };
}

export const S = {
  parseDate: sym("timekeeper.parse", "parse_date", "function", 42),
  splitIso: sym("timekeeper.parse", "_split_iso", "function", 15),
  parseTime: sym("timekeeper.parse", "parse_time", "function", 88),
  fmtModule: sym("timekeeper.fmt", "<module>", "function", 1),
  formatDuration: sym("timekeeper.fmt", "format_duration", "function", 30),
  rruleNext: sym("timekeeper.recur", "RRule.next", "method", 64),
  expandRrule: sym("timekeeper.recur", "expand_rrule", "function", 101),
  byMonth: sym("timekeeper.recur", "_by_month", "function", 140),
  foldOffset: sym("timekeeper.tz.fold", "_fold_offset", "function", 18),
  resolveFold: sym("timekeeper.tz.fold", "resolve_fold", "function", 44),
  getZone: sym("timekeeper.tz.zones", "get_zone", "function", 25),
  relative: sym("timekeeper.humanize", "relative", "function", 33),
  cliMain: sym("timekeeper.cli", "main", "function", 10),
  isoWeek: sym("timekeeper.calendars.iso", "iso_week", "function", 22),
  toIsoCalendar: sym("timekeeper.calendars.iso", "to_iso_calendar", "function", 51),
  instant: sym("timekeeper.core", "Instant", "class", 8),
} as const;

export interface ChangeSpec {
  symbol: SymbolSpec;
  baseLines: [number, number];
  headLines: [number, number];
}

/** symbol.changed, in emission order. `fmtModule` is a module-level change (a constant). */
export const CHANGES: readonly ChangeSpec[] = [
  { symbol: S.parseDate, baseLines: [42, 86], headLines: [42, 97] },
  { symbol: S.splitIso, baseLines: [15, 38], headLines: [15, 40] },
  { symbol: S.fmtModule, baseLines: [1, 12], headLines: [1, 12] },
  { symbol: S.formatDuration, baseLines: [30, 58], headLines: [30, 52] },
  { symbol: S.expandRrule, baseLines: [101, 138], headLines: [101, 129] },
  { symbol: S.byMonth, baseLines: [140, 171], headLines: [131, 160] },
  { symbol: S.foldOffset, baseLines: [18, 40], headLines: [18, 43] },
];

export const MODULE_LEVEL_CHANGES: readonly string[] = ["timekeeper.fmt"];

/** Reverse dependents of the changed symbols inside the story, with blast distance. */
export const STORY_AFFECTED: readonly (readonly [SymbolSpec, number])[] = [
  [S.parseTime, 1],
  [S.cliMain, 1],
  [S.toIsoCalendar, 1],
  [S.relative, 1],
  [S.rruleNext, 1],
  [S.resolveFold, 1],
  [S.isoWeek, 2],
  [S.getZone, 2],
  [S.instant, 2],
];

/** Observed calls (caller → callee), emitted as `calls` edges by the selection-map pass. */
export const STORY_CALLS: readonly (readonly [SymbolSpec, SymbolSpec])[] = [
  [S.parseDate, S.splitIso],
  [S.parseTime, S.splitIso],
  [S.cliMain, S.parseDate],
  [S.toIsoCalendar, S.parseDate],
  [S.isoWeek, S.toIsoCalendar],
  [S.instant, S.parseDate],
  [S.relative, S.formatDuration],
  [S.expandRrule, S.rruleNext],
  [S.rruleNext, S.byMonth],
  [S.resolveFold, S.foldOffset],
  [S.getZone, S.resolveFold],
];

// ---------------------------------------------------------------------------------------------
// Tests and what each one observes

export type SelectionReason = "blast_radius" | "module_import" | "new_test" | "modified_test";

/** One traced call: arguments and result preview on each side (null = not observed). */
export interface Observation {
  symbol: SymbolSpec;
  args: string;
  base: string | null;
  /** Defaults to `base` (A′ normally agrees with A). */
  repeat?: string | null;
  head: string | null;
}

export interface TestSpec {
  id: string;
  module: string;
  file: string;
  name: string;
  line: number;
  reasons: readonly SelectionReason[];
  outcomes: { base: TestOutcome | null; repeat: TestOutcome | null; head: TestOutcome | null };
  cls: OutcomeClass;
  /** Typical duration on base, in ms. */
  ms: number;
  observations: readonly Observation[];
}

function test(
  module: string,
  name: string,
  line: number,
  cls: OutcomeClass,
  ms: number,
  observations: readonly Observation[],
  reasons: readonly SelectionReason[] = ["blast_radius"],
): TestSpec {
  const spec = STORY_MODULES.find((m) => m.name === module);
  if (spec === undefined) throw new Error(`unknown test module ${module}`);
  const outcomes = OUTCOMES[cls];
  if (outcomes === undefined) throw new Error(`no outcome pattern for class ${cls}`);
  return {
    id: `${spec.file}::${name}`,
    module,
    file: spec.file,
    name,
    line,
    reasons,
    outcomes,
    cls,
    ms,
    observations,
  };
}

const OUTCOMES: Readonly<Partial<Record<OutcomeClass, TestSpec["outcomes"]>>> = {
  P2P: { base: "passed", repeat: "passed", head: "passed" },
  F2P: { base: "failed", repeat: "failed", head: "passed" },
  P2F: { base: "passed", repeat: "passed", head: "failed" },
  new: { base: null, repeat: null, head: "passed" },
  modified: { base: "passed", repeat: "passed", head: "skipped" },
  flaky: { base: "passed", repeat: "failed", head: "passed" },
};

const same = (symbol: SymbolSpec, args: string, result: string): Observation => ({
  symbol,
  args,
  base: result,
  head: result,
});

export const T = {
  offsetAware: test("tests.test_parse", "test_offset_aware", 12, "F2P", 31, [
    {
      symbol: S.parseDate,
      args: "('2026-03-29T02:30+01:00',)",
      base: "datetime(2026, 3, 29, 2, 30)",
      head: "datetime(2026, 3, 29, 2, 30, tzinfo=+01:00)",
    },
    same(S.splitIso, "('2026-03-29T02:30+01:00',)", "('2026-03-29', '02:30', '+01:00')"),
  ]),
  offsetNegative: test("tests.test_parse", "test_offset_negative", 27, "F2P", 29, [
    {
      symbol: S.parseDate,
      args: "('2026-11-01T01:30-04:00',)",
      base: "datetime(2026, 11, 1, 1, 30)",
      head: "datetime(2026, 11, 1, 1, 30, tzinfo=-04:00)",
    },
    same(S.splitIso, "('2026-11-01T01:30-04:00',)", "('2026-11-01', '01:30', '-04:00')"),
  ]),
  naiveInput: test("tests.test_parse", "test_naive_input", 41, "P2P", 24, [
    same(S.parseDate, "('2026-10-13T09:00',)", "datetime(2026, 10, 13, 9, 0)"),
    same(S.splitIso, "('2026-10-13T09:00',)", "('2026-10-13', '09:00', None)"),
  ]),
  durationHours: test("tests.test_fmt", "test_format_duration_hours", 9, "P2F", 12, [
    { symbol: S.formatDuration, args: "(3600,)", base: "'1h 0m'", head: "'1h'" },
  ]),
  durationMinutes: test("tests.test_fmt", "test_format_duration_minutes", 18, "P2P", 11, [
    same(S.formatDuration, "(150,)", "'2m 30s'"),
  ]),
  dateLocale: test(
    "tests.test_fmt",
    "test_format_date_locale",
    30,
    "P2P",
    46,
    [],
    ["module_import"],
  ),
  dailyRule: test("tests.test_recur", "test_daily_rule", 11, "P2P", 214, [
    same(S.expandRrule, "(RRule(freq=DAILY, count=10),)", "list[datetime] (10 items)"),
    same(
      S.rruleNext,
      "(RRule(freq=DAILY), datetime(2026, 10, 13, 9, 0))",
      "datetime(2026, 10, 14, 9, 0)",
    ),
  ]),
  weeklyRule: test("tests.test_recur", "test_weekly_rule", 24, "P2P", 1, [
    same(S.expandRrule, "(RRule(freq=WEEKLY, count=4),)", "list[datetime] (4 items)"),
    same(S.byMonth, "(2026, 10)", "[5, 12, 19, 26]"),
  ]),
  monthlyEdge: test(
    "tests.test_recur",
    "test_monthly_edge",
    40,
    "modified",
    38,
    [
      {
        symbol: S.expandRrule,
        args: "(RRule(freq=MONTHLY, bymonthday=31, count=3),)",
        base: "list[datetime] (3 items)",
        head: null,
      },
      { symbol: S.byMonth, args: "(2026, 11)", base: "[]", head: null },
    ],
    ["blast_radius", "modified_test"],
  ),
  largeCount: test("tests.test_recur", "test_large_count", 57, "flaky", 870, [
    {
      symbol: S.expandRrule,
      args: "(RRule(freq=HOURLY, count=5000),)",
      base: "list[datetime] (5000 items, order digest 3f2a91c0)",
      repeat: "list[datetime] (5000 items, order digest 9c41d7e2)",
      head: "list[datetime] (5000 items, order digest 3f2a91c0)",
    },
  ]),
  springForward: test(
    "tests.test_dst",
    "test_spring_forward",
    8,
    "new",
    19,
    [
      {
        symbol: S.parseDate,
        args: "('2026-03-29T02:30', tz='Europe/Berlin')",
        base: null,
        head: "datetime(2026, 3, 29, 3, 30, tzinfo=+02:00)",
      },
      {
        symbol: S.resolveFold,
        args: "(datetime(2026, 3, 29, 2, 30), 'Europe/Berlin')",
        base: null,
        head: "datetime(2026, 3, 29, 3, 30)",
      },
    ],
    ["new_test"],
  ),
  foldResolution: test("tests.test_tz", "test_fold_resolution", 14, "P2P", 17, [
    same(
      S.resolveFold,
      "(datetime(2026, 10, 25, 2, 30), 'Europe/Berlin')",
      "datetime(2026, 10, 25, 2, 30, fold=0)",
    ),
    same(S.getZone, "('Europe/Berlin',)", "Zone('Europe/Berlin')"),
  ]),
  utcOffset: test("tests.test_tz", "test_utc_offset", 30, "P2P", 9, [
    {
      symbol: S.parseDate,
      args: "('2026-10-13T09:00+00:00',)",
      base: "datetime(2026, 10, 13, 9, 0)",
      head: "datetime(2026, 10, 13, 9, 0, tzinfo=UTC)",
    },
  ]),
  relativeHours: test("tests.test_humanize", "test_relative_hours", 16, "P2P", 14, [
    { symbol: S.relative, args: "(timedelta(hours=2),)", base: "'in 2h 0m'", head: "'in 2h'" },
    { symbol: S.formatDuration, args: "(7200,)", base: "'2h 0m'", head: "'2h'" },
  ]),
  cliParse: test("tests.test_cli", "test_cli_parse", 9, "P2P", 63, [
    same(S.cliMain, "(['parse', '2026-10-13T09:00Z'],)", "0"),
    {
      symbol: S.parseDate,
      args: "('2026-10-13T09:00Z',)",
      base: "datetime(2026, 10, 13, 9, 0)",
      head: "datetime(2026, 10, 13, 9, 0, tzinfo=UTC)",
    },
  ]),
  isoWeek: test("tests.test_calendars", "test_iso_week", 12, "P2P", 8, [
    same(S.isoWeek, "(datetime(2026, 10, 13),)", "(2026, 42, 2)"),
    same(
      S.toIsoCalendar,
      "(datetime(2026, 10, 13),)",
      "IsoCalendarDate(year=2026, week=42, weekday=2)",
    ),
  ]),
  isoRoundtrip: test("tests.test_calendars", "test_iso_calendar_roundtrip", 29, "P2P", 21, [
    same(
      S.toIsoCalendar,
      "(datetime(2026, 10, 13),)",
      "IsoCalendarDate(year=2026, week=42, weekday=2)",
    ),
    same(S.parseDate, "('2026-10-13',)", "datetime(2026, 10, 13, 0, 0)"),
  ]),
} as const;

/** The story's selected tests, in selection (and base/head run) order. */
export const STORY_TESTS: readonly TestSpec[] = [
  T.offsetAware,
  T.offsetNegative,
  T.naiveInput,
  T.durationHours,
  T.durationMinutes,
  T.dateLocale,
  T.dailyRule,
  T.weeklyRule,
  T.monthlyEdge,
  T.largeCount,
  T.springForward,
  T.foldResolution,
  T.utcOffset,
  T.relativeHours,
  T.cliParse,
  T.isoWeek,
  T.isoRoundtrip,
];

/** Flips are re-run k more times on both sides before they become evidence (ARCHITECTURE §4.2). */
export const RERUNS = 2;

/** Symbols a story test's traces reach. Only blast-radius functions are traced (ARCHITECTURE §4.3). */
export function storyCovers(test: TestSpec): readonly SymbolSpec[] {
  const out: SymbolSpec[] = [];
  for (const obs of test.observations) if (!out.includes(obs.symbol)) out.push(obs.symbol);
  return out;
}

// ---------------------------------------------------------------------------------------------
// Claims and verdicts

export interface ClaimSpec extends Claim {
  verdict: VerdictValue;
  agent: string;
}

function claim(
  id: string,
  kind: ClaimKind,
  text: string,
  targets: Claim["targets"],
  verdict: VerdictValue,
  agent: string,
): ClaimSpec {
  return { id, text, kind, targets, source: "description", verdict, agent };
}

export const CLAIMS: readonly ClaimSpec[] = [
  claim(
    "C1",
    "fix",
    "parse_date returns timezone-aware datetimes when the input carries a UTC offset.",
    [{ file: S.parseDate.file, symbol: S.parseDate.id }],
    "supported",
    "a06",
  ),
  claim(
    "C2",
    "perf",
    "expand_rrule is about twice as fast for daily rules.",
    [{ file: S.expandRrule.file, symbol: S.expandRrule.id }],
    "supported",
    "a07",
  ),
  claim(
    "C3",
    "refactor",
    "format_duration is refactored with no behaviour change.",
    [{ file: S.formatDuration.file, symbol: S.formatDuration.id }],
    "contradicted",
    "a08",
  ),
  claim(
    "C4",
    "deps",
    "Adds example-tzdb so zone data is available on every platform.",
    [{ file: "pyproject.toml" }],
    "supported",
    "a09",
  ),
];

export const NEW_DEPENDENCY = { package: "example-tzdb", version: "1.2.0" } as const;

export interface InvariantSpec {
  name: string;
  result: "pass" | "fail";
  message: string;
}

export const INVARIANTS: readonly InvariantSpec[] = [
  {
    name: "no_network",
    result: "pass",
    message: "No network attempts on any side; network enforced at L3.",
  },
  {
    name: "no_new_dependencies",
    result: "fail",
    message: `Policy forbids new runtime dependencies; head adds ${NEW_DEPENDENCY.package} ${NEW_DEPENDENCY.version}.`,
  },
  { name: "public_api_stable", result: "pass", message: "No breaking change in the public API." },
  { name: "forbidden_paths", result: "pass", message: "No protected path was changed." },
];

// ---------------------------------------------------------------------------------------------
// Agents

export interface AgentSpec {
  id: string;
  role: AgentRole;
  model: string;
  promptVersion: string;
  slot: number;
}

const MODEL_BY_ROLE: Record<AgentRole, string> = {
  read: "claude-haiku-5-5",
  build: "claude-sonnet-5-5",
  probe: "claude-sonnet-5-5",
  review: "claude-opus-5-5",
  gap: "claude-opus-5-5",
  qa: "claude-opus-5-5",
};

const agent = (n: number, role: AgentRole, promptVersion: string): AgentSpec => ({
  id: `a${String(n).padStart(2, "0")}`,
  role,
  model: MODEL_BY_ROLE[role],
  promptVersion,
  slot: n - 1,
});

export const AGENTS = {
  reader: agent(1, "read", "reader/1"),
  probes: [
    agent(2, "probe", "probe/1"),
    agent(3, "probe", "probe/1"),
    agent(4, "probe", "probe/1"),
    agent(5, "probe", "probe/1"),
  ],
  reviewers: [
    agent(6, "review", "reviewer/1"),
    agent(7, "review", "reviewer/1"),
    agent(8, "review", "reviewer/1"),
    agent(9, "review", "reviewer/1"),
  ],
  swap: agent(10, "review", "reviewer/1"),
  gap: agent(11, "gap", "gap/1"),
  qa: agent(12, "qa", "qa/1"),
} as const;

/** One probe writer per changed function; none of their probes diverge (see README). */
export const PROBE_TARGETS: readonly SymbolSpec[] = [
  S.parseDate,
  S.formatDuration,
  S.expandRrule,
  S.foldOffset,
];

/**
 * Flat synthetic token rates (USD per million tokens) for `cost.estimate`. These are not prices
 * of any real model; the fixture only needs plausible magnitudes.
 */
export const SYNTHETIC_RATES = { input: 2, output: 8, cacheRead: 0.2 } as const;
