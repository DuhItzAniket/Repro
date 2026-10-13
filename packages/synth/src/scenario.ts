/**
 * Plays the story through the seven pipeline stages and writes the event log a real engine
 * would produce for it: three sandboxes running concurrently, agents working in parallel,
 * evidence created before anything cites it, and result-bearing events whose envelope status
 * follows the check model (ADR-0015).
 */
import type {
  AgentStatePayload,
  ArtifactRef,
  CardPublishedPayload,
  Evidence,
  EvidenceType,
  MissingReason,
  Origin,
  ReproEvent,
  Side,
  Stability,
  Stage,
  Status,
  Target,
  TestOutcome,
} from "@repro/events";
import { ulid } from "./ids";
import { buildRepo, type Repo } from "./repo";
import { Rng } from "./rng";
import {
  AGENTS,
  type AgentSpec,
  BASE_REF,
  CHANGES,
  CLAIMS,
  type ClaimSpec,
  HEAD_REF,
  INVARIANTS,
  MODULE_LEVEL_CHANGES,
  NEW_DEPENDENCY,
  PLATFORM,
  PR_NUMBER,
  PR_TITLE,
  PROBE_TARGETS,
  PRODUCER,
  PYTHON_VERSION,
  REPO_NAME,
  REPRO_VERSION,
  RERUNS,
  S,
  STORY_AFFECTED,
  SYNTHETIC_RATES,
  type SymbolSpec,
  T,
  type TestSpec,
} from "./story";
import { type Draft, Timeline } from "./timeline";

/** Sizes and pacing of a synthetic run. The story is the same for every profile. */
export interface Profile {
  readonly name: string;
  /** Python modules in the dependency graph (the header's FILES counter). */
  readonly files: number;
  /** `graph.edge` events in total: imports, observed calls and coverage. */
  readonly edges: number;
  /** Blast-radius symbols outside the story. */
  readonly fillerSymbols: number;
  /** Selected tests outside the story; they pass on every side. */
  readonly fillerTests: number;
  /** Own duration range of each filler test, in ms. */
  readonly fillerTestMs: readonly [number, number];
  /** Build-stage spans over which graph nodes, then import edges, stream in. */
  readonly graphNodesMs: number;
  readonly graphEdgesMs: number;
  /** Per-test overhead (fixtures, tracer flush) added to each test's own duration. */
  readonly testOverheadMs: readonly [number, number];
  /** Pause between consecutive tests on one side (result reporting). */
  readonly testGapMs: readonly [number, number];
  /** Pytest collection time on each side before the first test starts. */
  readonly collectMs: number;
}

/** What the generator intended. Tests recount every number independently from the events. */
export interface RunSummary {
  events: number;
  claims: number;
  agents: number;
  files: number;
  graphNodes: number;
  graphEdges: number;
  selectedTests: number;
  /** Result-bearing events: `diff.*` and `invariant.result` (ADR-0015). */
  checks: number;
  passed: number;
  flagged: number;
  /** Checks that could not be assessed (the index's hollow cells). */
  unassessed: number;
  evidence: number;
  missing: number;
  card: CardPublishedPayload;
  durationMs: number;
}

export interface SyntheticRun {
  readonly profile: Profile;
  readonly seed: number;
  readonly events: ReproEvent[];
  readonly summary: RunSummary;
}

/** 2026-10-13T09:00:00.000Z. Fixtures have a fixed start so the log is byte-stable. */
export const RUN_START_MS = Date.UTC(2026, 9, 13, 9, 0, 0);

const SIDES: readonly Side[] = ["base", "base_repeat", "head"];
const STAGES: readonly Stage[] = ["read", "build", "run", "diff", "check", "review", "card"];
/** Files in each snapshot besides Python modules (README, pyproject.toml, docs, …). */
const NON_PYTHON_FILES = 34;
/** Above this many selected tests the feed logs summaries instead of single tests. */
const VERBOSE_TEST_LIMIT = 100;

interface EvidenceRef {
  readonly id: string;
  readonly draft: Draft;
  readonly summary: string;
}

interface ScriptStep {
  /** Delay before this step, in ms. */
  readonly after: number;
  readonly state: AgentStatePayload["state"];
  readonly tool?: string;
  readonly detail: string;
  readonly progress: number;
  /** Extra events emitted at this step's time (claims, rejections, sub-agents). */
  readonly also?: (at: number) => void;
}

interface GapItem {
  readonly ref: EvidenceRef;
  /** The supported claim that explains this difference, or null if none does. */
  readonly by: string | null;
}

const sha7 = (sha: string): string => sha.slice(0, 7);
const round = (value: number, digits: number): number => {
  const scale = 10 ** digits;
  return Math.round(value * scale) / scale;
};

function outcomeStatus(outcome: TestOutcome): Status {
  if (outcome === "passed" || outcome === "xfailed") return "ok";
  if (outcome === "skipped") return "warn";
  return "fail";
}

function verdictStatus(claim: ClaimSpec): Status {
  if (claim.verdict === "supported") return "ok";
  return claim.verdict === "contradicted" ? "fail" : "warn";
}

class RunBuilder {
  readonly tl = new Timeline();
  readonly runId: string;
  readonly repo: Repo;
  private readonly baseSha: string;
  private readonly headSha: string;
  private readonly rng: Rng;
  private readonly time: Rng;
  private readonly evidenceIds: Rng;
  private readonly stageStarts = new Map<Stage, Draft>();
  private readonly spawned = new Map<string, Draft>();
  private readonly outcomeEvidence = new Map<TestSpec, EvidenceRef>();
  private readonly found: {
    tamper?: EvidenceRef;
    parse?: EvidenceRef;
    fmt?: EvidenceRef;
    deps?: EvidenceRef;
    perf?: EvidenceRef;
  } = {};
  private missingCount = 0;
  private swapEnd = 0;

  constructor(
    private readonly profile: Profile,
    seed: number,
  ) {
    this.rng = new Rng(seed);
    this.time = this.rng.fork("time");
    this.evidenceIds = this.rng.fork("evidence-ids");
    this.runId = `run_${ulid(RUN_START_MS, this.rng.fork("run-id"))}`;
    const shas = this.rng.fork("shas");
    this.baseSha = shas.hex(40);
    this.headSha = shas.hex(40);
    this.repo = buildRepo(profile, this.rng.fork("repo"));
  }

  get missingItems(): number {
    return this.missingCount;
  }

  // -------------------------------------------------------------------------------------------
  // Small emitters

  private jitter(value: number, spread: number): number {
    return Math.max(0, Math.round(value + this.time.int(-spread, spread)));
  }

  private log(
    at: number,
    stage: Stage,
    message: string,
    level: "info" | "warning" | "error" = "info",
  ): void {
    const status: Status = level === "error" ? "fail" : level === "warning" ? "warn" : "ok";
    this.tl.emit(at, "log.line", stage, { level, verb: stage, message }, { status });
  }

  private stageStart(at: number, stage: Stage): void {
    const index = STAGES.indexOf(stage);
    const draft = this.tl.emit(at, "stage.started", stage, { index }, { status: "start" });
    this.stageStarts.set(stage, draft);
  }

  private stageEnd(at: number, stage: Stage): number {
    const start = this.stageStarts.get(stage);
    if (start === undefined) throw new Error(`stage ${stage} ended before it started`);
    this.tl.emit(at, "stage.finished", stage, { duration_ms: at - start.at }, { parent: start });
    return at;
  }

  private missing(
    at: number,
    stage: Stage,
    reason: MissingReason,
    targets: Target[],
    detail: string,
    resolution: string | null,
  ): void {
    this.missingCount++;
    this.tl.emit(
      at,
      "missing.recorded",
      stage,
      { missing: { reason, targets, detail, resolution } },
      { status: "warn", target: targets[0] ?? null },
    );
  }

  private evidence(
    at: number,
    stage: "build" | "run" | "diff" | "check",
    type: EvidenceType,
    targets: Target[],
    summary: string,
    data: Record<string, unknown>,
    component: string,
    options: { stability?: Stability; origin?: Origin; artifacts?: ArtifactRef[] } = {},
  ): EvidenceRef {
    const id = `ev_${ulid(RUN_START_MS + at, this.evidenceIds)}`;
    const evidence: Evidence = {
      id,
      run_id: this.runId,
      type,
      targets,
      summary,
      data,
      artifacts: options.artifacts ?? [],
      stability: options.stability ?? "stable",
      origin: options.origin ?? "introduced",
      produced_by: { component, version: REPRO_VERSION },
      seq: 1, // replaced by the event's own seq once the writer has ordered the log
    };
    const draft = this.tl.emit(
      at,
      "evidence.created",
      stage,
      { evidence },
      { target: targets[0] ?? null },
    );
    return { id, draft, summary };
  }

  private spawn(at: number, stage: Stage, agent: AgentSpec): Draft {
    const draft = this.tl.emit(
      at,
      "agent.spawned",
      stage,
      {
        role: agent.role,
        model: agent.model,
        prompt_version: agent.promptVersion,
        slot: agent.slot,
      },
      { agent: agent.id, status: "start" },
    );
    this.spawned.set(agent.id, draft);
    return draft;
  }

  private agentState(
    at: number,
    stage: Stage,
    agent: AgentSpec,
    step: Omit<ScriptStep, "after">,
  ): void {
    const spawned = this.spawned.get(agent.id);
    if (spawned === undefined) throw new Error(`${agent.id} acts before it is spawned`);
    const status: Status =
      step.state === "done" ? "ok" : step.state === "failed" ? "fail" : "progress";
    this.tl.emit(
      at,
      "agent.state",
      stage,
      { state: step.state, tool: step.tool ?? null, detail: step.detail, progress: step.progress },
      { agent: agent.id, status, parent: spawned },
    );
  }

  /** Spawns `agent` at `at`, plays its steps, and returns the time of the last one. */
  private script(at: number, stage: Stage, agent: AgentSpec, steps: readonly ScriptStep[]): number {
    this.spawn(at, stage, agent);
    let t = at;
    for (const step of steps) {
      t += step.after;
      this.agentState(t, stage, agent, step);
      step.also?.(t);
    }
    return t;
  }

  /** Client-side token estimate when an agent finishes (synthetic rates, see story.ts). */
  private cost(at: number, stage: Stage, agent: AgentSpec): void {
    const tokens = this.rng.fork(`cost/${agent.id}`);
    const input = tokens.int(6_000, 42_000);
    const output = tokens.int(300, 2_400);
    const cacheRead = tokens.int(0, 18_000);
    const usd =
      (input * SYNTHETIC_RATES.input +
        output * SYNTHETIC_RATES.output +
        cacheRead * SYNTHETIC_RATES.cacheRead) /
      1e6;
    this.tl.emit(
      at,
      "cost.estimate",
      stage,
      {
        model: agent.model,
        input_tokens: input,
        output_tokens: output,
        cache_read_tokens: cacheRead,
        usd: round(usd, 4),
        estimate: true,
      },
      { agent: agent.id },
    );
  }

  // -------------------------------------------------------------------------------------------
  // read

  read(at: number): number {
    this.tl.emit(
      at,
      "run.started",
      "read",
      {
        repo: { name: REPO_NAME, url: null },
        base: { ref: BASE_REF, sha: this.baseSha },
        head: { ref: HEAD_REF, sha: this.headSha },
        pr: { title: PR_TITLE, number: PR_NUMBER, url: null },
        mode: { deterministic_only: false, sandbox_backend: "docker" },
      },
      { status: "start" },
    );
    this.stageStart(at + 15, "read");
    this.log(at + 40, "read", `PR #${PR_NUMBER} · ${PR_TITLE}`);
    this.log(
      at + 90,
      "read",
      `base ${BASE_REF} ${sha7(this.baseSha)} · head ${HEAD_REF} ${sha7(this.headSha)}`,
    );
    const reader = AGENTS.reader;
    const claimSteps: ScriptStep[] = CLAIMS.map((claim, i) => ({
      after: this.jitter(260, 60),
      state: "tool_call",
      tool: "mcp__repro__emit_claim",
      detail: `emit_claim(${claim.id}, kind="${claim.kind}")`,
      progress: round(0.55 + 0.1 * i, 2),
      also: (t: number) => {
        const { verdict: _verdict, agent: _agent, ...payload } = claim;
        this.tl.emit(
          t,
          "claim.extracted",
          "read",
          { claim: payload },
          {
            agent: reader.id,
            target: claim.targets[0] ?? null,
          },
        );
        this.log(t + 10, "read", `${claim.id} ${claim.kind} · ${claim.text}`);
      },
    }));
    const end = this.script(at + 120, "read", reader, [
      { after: 60, state: "thinking", detail: "task = load_task(run)", progress: 0.05 },
      {
        after: this.jitter(380, 80),
        state: "tool_call",
        tool: "mcp__repro__read_pr",
        detail: `pr = read_pr(${PR_NUMBER})`,
        progress: 0.15,
      },
      {
        after: this.jitter(700, 120),
        state: "tool_call",
        tool: "mcp__repro__read_diff",
        detail: "diff = read_diff(base, head)",
        progress: 0.3,
      },
      {
        after: this.jitter(820, 150),
        state: "thinking",
        detail: "claims = split_claims(pr.body)",
        progress: 0.45,
      },
      ...claimSteps,
      { after: 240, state: "done", detail: `${CLAIMS.length} claims`, progress: 1 },
    ]);
    this.cost(end + 5, "read", reader);
    this.log(end + 30, "read", `${CLAIMS.length} claims extracted`);
    return this.stageEnd(end + 80, "read");
  }

  // -------------------------------------------------------------------------------------------
  // build

  private blastSymbols(): readonly SymbolSpec[] {
    const changed = CHANGES.map((c) => c.symbol).filter((s) => s.name !== "<module>");
    return [...changed, ...STORY_AFFECTED.map(([s]) => s), ...this.repo.fillerSymbols];
  }

  graphNodeCount(): number {
    return this.repo.modules.length + this.blastSymbols().length + this.repo.tests.length;
  }

  build(at: number): number {
    this.stageStart(at, "build");
    const files = this.repo.modules.length + NON_PYTHON_FILES;
    this.log(at + 60, "build", `snapshot base ${sha7(this.baseSha)} via git archive (no .git)`);
    this.tl.emit(at + 420, "snapshot.ready", "build", {
      side: "base",
      sha: this.baseSha,
      file_count: files - 1, // tests/test_dst.py is new on head
      tree_sha256: this.rng.fork("tree/base").hex(64),
    });
    this.log(at + 470, "build", `snapshot head ${sha7(this.headSha)} via git archive (no .git)`);
    this.tl.emit(at + 760, "snapshot.ready", "build", {
      side: "head",
      sha: this.headSha,
      file_count: files,
      tree_sha256: this.rng.fork("tree/head").hex(64),
    });
    this.log(at + 820, "build", "static analysis: symbols, imports, public API");

    // Nodes stream in first (modules, then blast-radius symbols and tests), then import edges.
    type GraphNode = {
      id: string;
      type: "module" | "class" | "function" | "method" | "test";
      name: string;
      file: string;
      line: number | null;
    };
    const nodes: GraphNode[] = [
      ...this.repo.modules.map(
        (m): GraphNode => ({ id: m.name, type: "module", name: m.name, file: m.file, line: null }),
      ),
      ...this.blastSymbols().map(
        (s): GraphNode => ({ id: s.id, type: s.type, name: s.name, file: s.file, line: s.line }),
      ),
      ...this.repo.tests.map(
        (t): GraphNode => ({ id: t.id, type: "test", name: t.name, file: t.file, line: t.line }),
      ),
    ];
    const nodesFrom = at + 900;
    nodes.forEach((node, i) => {
      const t = nodesFrom + Math.floor((i * this.profile.graphNodesMs) / nodes.length);
      this.tl.emit(t, "graph.node", "build", { node });
    });
    const edgesFrom = nodesFrom + this.profile.graphNodesMs + 20;
    const imports = this.repo.imports;
    imports.forEach(([source, target], i) => {
      const t = edgesFrom + Math.floor((i * this.profile.graphEdgesMs) / imports.length);
      this.tl.emit(t, "graph.edge", "build", { source, target, type: "imports" });
    });
    let t = edgesFrom + this.profile.graphEdgesMs + 40;
    this.log(
      t,
      "build",
      `import graph: ${this.repo.modules.length} modules · ${imports.length} imports`,
    );

    for (const change of CHANGES) {
      t += this.jitter(90, 30);
      const s = change.symbol;
      this.tl.emit(
        t,
        "symbol.changed",
        "build",
        {
          symbol_id: s.id,
          change: "modified",
          file: s.file,
          base_lines: change.baseLines,
          head_lines: change.headLines,
          previous_symbol_id: null,
        },
        { target: { file: s.file, symbol: s.id } },
      );
      this.log(
        t + 5,
        "build",
        `changed ${s.file}: ${s.name === "<module>" ? "module body" : s.name}`,
      );
    }
    const affected = [
      ...STORY_AFFECTED.map(([s, distance]) => ({ symbol_id: s.id, distance })),
      ...this.repo.fillerSymbols.map((s) => ({ symbol_id: s.id, distance: s.distance })),
    ];
    t += 160;
    this.tl.emit(t, "blast.computed", "build", {
      changed: CHANGES.map((c) => c.symbol.id),
      affected,
      module_level_changes: [...MODULE_LEVEL_CHANGES],
    });
    const blastFiles = new Set(this.blastSymbols().map((s) => s.file));
    this.log(
      t + 10,
      "build",
      `blast radius: ${CHANGES.length} changed · ${affected.length} affected · ${blastFiles.size} files`,
    );

    t += 200;
    for (const side of SIDES) {
      t += this.jitter(140, 40);
      this.tl.emit(t, "sandbox.ready", "build", {
        side,
        backend: "docker",
        isolation_level: "L3",
        network: "enforced",
        platform: PLATFORM,
      });
      this.log(t + 5, "build", `sandbox ${side}: docker · L3 · network none`);
    }
    const baseFrom = t + 60;
    this.log(baseFrom, "build", "provision base: uv sync --offline (cache warm)");
    const baseEnv = baseFrom + this.jitter(840, 120);
    this.tl.emit(baseEnv, "env.provisioned", "build", {
      side: "base",
      project_kind: "uv",
      python_version: PYTHON_VERSION,
      lock_sha256: this.rng.fork("lock/base").hex(64),
      installed_packages: 23,
      cache_hit: true,
      duration_ms: baseEnv - baseFrom,
    });
    const headFrom = baseEnv + 10;
    this.log(headFrom, "build", "provision head: lockfile changed, cache miss");
    const headEnv = headFrom + this.jitter(6100, 600);
    this.tl.emit(headEnv, "env.provisioned", "build", {
      side: "head",
      project_kind: "uv",
      python_version: PYTHON_VERSION,
      lock_sha256: this.rng.fork("lock/head").hex(64),
      installed_packages: 24,
      cache_hit: false,
      duration_ms: headEnv - headFrom,
    });
    this.log(headEnv + 10, "build", `environments ready · Python ${PYTHON_VERSION}`);
    return this.stageEnd(headEnv + 60, "build");
  }

  // -------------------------------------------------------------------------------------------
  // run

  run(at: number): number {
    this.stageStart(at, "run");
    this.log(at + 40, "run", "selection map: tracing base to map tests to functions");
    const observed = [
      ...this.repo.coverEdges.map(([source, target]) => ({
        source,
        target,
        type: "covers" as const,
      })),
      ...this.repo.callEdges.map(([source, target]) => ({
        source,
        target,
        type: "calls" as const,
      })),
    ];
    const mapMs = 1400;
    observed.forEach((edge, i) => {
      this.tl.emit(at + 120 + Math.floor((i * mapMs) / observed.length), "graph.edge", "run", edge);
    });
    let t = at + 120 + mapMs + 30;
    const verbose = this.repo.tests.length <= VERBOSE_TEST_LIMIT;
    for (const test of this.repo.tests) {
      t += verbose ? this.jitter(45, 15) : 1;
      const symbols = (this.repo.covers.get(test) ?? []).map((s) => s.id);
      this.tl.emit(
        t,
        "test.selected",
        "run",
        { reasons: [...test.reasons], symbols },
        { target: { test: test.id } },
      );
    }
    t += 40;
    this.log(t, "run", `selected ${this.repo.tests.length} tests reaching the blast radius`);
    this.missing(
      t + 20,
      "run",
      "no_covering_test",
      [{ file: S.foldOffset.file, symbol: S.foldOffset.id }],
      "_fold_offset changed, but no selected test reaches it.",
      "Add a test that resolves a time inside a DST fold.",
    );
    this.log(t + 25, "run", "no test reaches tz/fold.py:_fold_offset", "warning");

    // Probe writers work while the sandboxes run tests.
    const probesFrom = t + 120;
    const probeEnds = PROBE_TARGETS.map((target, i) => {
      const agent = AGENTS.probes[i];
      if (agent === undefined) throw new Error(`no probe writer for ${target.id}`);
      const end = this.script(
        probesFrom + i * 140,
        "run",
        agent,
        this.probeScript(target, i === 3),
      );
      this.cost(end + 5, "run", agent);
      return end + 5;
    });

    // Three sandboxes run concurrently. A and H share the test order; A′ uses another seed and order.
    const execFrom = t + 300;
    const sideEnds = SIDES.map((side, i) => this.runSide(execFrom + i * 35, side));
    const flips = this.repo.tests.filter((x) => x.cls === "F2P" || x.cls === "P2F");
    const rerunFrom = Math.max(...sideEnds) + 120;
    this.log(
      rerunFrom,
      "run",
      `re-running ${flips.length} flipped tests ×${RERUNS} on base and head`,
    );
    let rerunEnd = rerunFrom;
    for (const side of ["base", "head"] as const) {
      let s = rerunFrom + 40;
      for (let attempt = 2; attempt <= RERUNS + 1; attempt++) {
        for (const test of flips) s = this.runTest(s, side, test, attempt) + this.jitter(30, 10);
      }
      rerunEnd = Math.max(rerunEnd, s);
    }

    // Untraced, interleaved perf runs (ABBA) for the tests behind the perf claim.
    let p = rerunEnd + 100;
    this.log(p, "run", "perf: interleaved ABBA runs, untraced, 5 per side");
    const medians: readonly (readonly [TestSpec, number, number])[] = [
      [T.dailyRule, 214, 105],
      [T.weeklyRule, 1.1, 1.1],
    ];
    for (const [test, base, head] of medians) {
      for (let rep = 1; rep <= 5; rep++) {
        const order = rep % 2 === 1 ? (["base", "head"] as const) : (["head", "base"] as const);
        for (const side of order) {
          const median = side === "base" ? base : head;
          const duration = round(median * (1 + (this.time.float() - 0.5) * 0.06), 1);
          p += Math.max(2, Math.round(duration)) + this.jitter(25, 8);
          this.tl.emit(
            p,
            "perf.sample",
            "run",
            { side, repetition: rep, duration_ms: duration },
            {
              target: { test: test.id },
            },
          );
        }
      }
    }
    const end = Math.max(p, ...probeEnds) + 150;
    this.log(end - 60, "run", "probes: 4 written · 3 kept · 0 differences");
    return this.stageEnd(end, "run");
  }

  private probeScript(target: SymbolSpec, discarded: boolean): ScriptStep[] {
    const probeId = `probe_${target.name.replace(/^_/, "")}_edges`;
    return [
      { after: 40, state: "thinking", detail: `src = read_symbol("${target.id}")`, progress: 0.1 },
      {
        after: this.jitter(700, 200),
        state: "tool_call",
        tool: "mcp__repro__read_symbol",
        detail: `read_symbol("${target.id}")`,
        progress: 0.25,
      },
      {
        after: this.jitter(900, 250),
        state: "tool_call",
        tool: "mcp__repro__related_tests",
        detail: `tests = related_tests("${target.name}")`,
        progress: 0.4,
      },
      {
        after: this.jitter(1800, 400),
        state: "thinking",
        detail: `probe = write_probe(${target.name}, inputs=edge_cases)`,
        progress: 0.6,
      },
      {
        after: this.jitter(1500, 300),
        state: "tool_call",
        tool: "mcp__repro__submit_probe",
        detail: `submit_probe("${probeId}")`,
        progress: 0.8,
      },
      {
        after: this.jitter(1200, 300),
        state: "tool_call",
        tool: "mcp__repro__run_probe",
        detail: `result = run_probe("${probeId}", base, head)`,
        progress: 0.9,
      },
      {
        after: this.jitter(400, 100),
        state: "done",
        detail: discarded ? "discarded: not deterministic across A and A′" : "kept · no difference",
        progress: 1,
      },
    ];
  }

  private outcomeOn(side: Side, test: TestSpec): TestOutcome | null {
    if (side === "base") return test.outcomes.base;
    return side === "base_repeat" ? test.outcomes.repeat : test.outcomes.head;
  }

  /** One side's first pass: collection, then every runnable selected test in order. */
  private runSide(at: number, side: Side): number {
    const order =
      side === "base_repeat" ? this.time.shuffled(this.repo.tests) : [...this.repo.tests];
    const runnable = order.filter((test) => this.outcomeOn(side, test) !== null);
    this.log(at, "run", `${side}: collecting ${runnable.length} tests`);
    let t = at + this.jitter(this.profile.collectMs, Math.floor(this.profile.collectMs / 8));
    const [gapLo, gapHi] = this.profile.testGapMs;
    for (const test of runnable) t = this.runTest(t, side, test, 1) + this.time.int(gapLo, gapHi);
    const failed = runnable.filter((test) => this.outcomeOn(side, test) === "failed").length;
    this.log(
      t + 10,
      "run",
      `${side}: ${runnable.length} run · ${failed} failed`,
      failed > 0 ? "warning" : "info",
    );
    return t + 10;
  }

  private runTest(at: number, side: Side, test: TestSpec, attempt: number): number {
    const outcome = this.outcomeOn(side, test);
    if (outcome === null) return at;
    const target: Target = { test: test.id };
    const started = this.tl.emit(
      at,
      "test.started",
      "run",
      { side, attempt },
      { target, status: "start" },
    );
    const [lo, hi] = this.profile.testOverheadMs;
    const own =
      outcome === "skipped" ? 0 : Math.max(1, this.jitter(test.ms, Math.ceil(test.ms * 0.08)));
    const duration = own + this.time.int(lo, hi);
    if (attempt === 1 && outcome !== "skipped") {
      for (const obs of test.observations) {
        const result =
          side === "base" ? obs.base : side === "head" ? obs.head : (obs.repeat ?? obs.base);
        if (result === null) continue;
        const calls = this.time.int(1, 4);
        for (let call = 0; call < calls; call++) {
          const ts = at + 1 + Math.floor(((call + 1) * Math.max(0, duration - 2)) / (calls + 1));
          this.tl.emit(
            ts,
            "trace.sample",
            "run",
            {
              side,
              symbol_id: obs.symbol.id,
              call_index: call,
              args_preview: obs.args,
              result_preview: result,
              raised: null,
            },
            { target: { file: obs.symbol.file, symbol: obs.symbol.id, test: test.id } },
          );
        }
      }
    }
    this.tl.emit(
      at + duration,
      "test.finished",
      "run",
      { side, attempt, outcome, duration_ms: duration },
      { target, status: outcomeStatus(outcome), parent: started },
    );
    if (attempt === 1 && this.repo.tests.length <= VERBOSE_TEST_LIMIT) {
      if (outcome === "failed") {
        this.log(at + duration + 2, "run", `${side}: ${test.id} failed`, "warning");
      } else if (side === "head") {
        this.log(at + duration + 2, "run", `head: ${test.id} ${outcome} (${duration} ms)`);
      }
    }
    return at + duration;
  }

  // -------------------------------------------------------------------------------------------
  // diff

  diff(at: number): number {
    this.stageStart(at, "diff");
    this.log(at + 30, "diff", "comparing outcomes, behaviour, dependencies and timings");
    let t = at + 80;
    const step = this.repo.tests.length > VERBOSE_TEST_LIMIT ? 2 : 45;
    for (const test of this.repo.tests) t = this.diffOutcome(t + step, test);

    // Test tampering: a skip marker added to a test that the change breaks.
    t += 60;
    const edge = T.monthlyEdge;
    const tamper = this.evidence(
      t,
      "diff",
      "test_change",
      [{ file: edge.file, test: edge.id }],
      `${edge.id}: @pytest.mark.skip added on head; the base version of the test fails on head`,
      { change: "skip_added", test: edge.id },
      "diff.tests",
    );
    this.found.tamper = tamper;
    this.tl.emit(
      t + 15,
      "diff.tests",
      "diff",
      {
        evidence_id: tamper.id,
        file: edge.file,
        test: edge.id,
        change: "skip_added",
        detail: "@pytest.mark.skip added; the base version fails on head",
      },
      { target: { file: edge.file, test: edge.id }, status: "fail", parent: tamper.draft },
    );
    this.log(t + 20, "diff", `test change: skip added to ${edge.name}`, "error");

    // Behaviour: two stable differences and one masked as unstable (A and A′ disagree).
    t += 120;
    this.found.parse = this.diffBehaviour(t, S.parseDate, T.cliParse, "result_changed", "stable");
    t += 110;
    this.found.fmt = this.diffBehaviour(
      t,
      S.formatDuration,
      T.relativeHours,
      "result_changed",
      "stable",
    );
    t += 110;
    this.diffBehaviour(t, S.expandRrule, T.largeCount, "order_only", "unstable");
    this.missing(
      t + 30,
      "diff",
      "unstable_observation",
      [{ symbol: S.expandRrule.id, test: T.largeCount.id }],
      "expand_rrule result order differs between A and A′; masked from the comparison.",
      null,
    );
    this.missing(
      t + 40,
      "diff",
      "unstable_observation",
      [{ test: T.largeCount.id }],
      "test_large_count passed on base and failed on the base repeat (A′).",
      "Stabilise the test, then run Repro again.",
    );

    // Dependencies.
    t += 140;
    const { package: pkg, version } = NEW_DEPENDENCY;
    const deps = this.evidence(
      t,
      "diff",
      "dep_diff",
      [{ file: "pyproject.toml" }],
      `${pkg} ${version} added to runtime dependencies (uv.lock)`,
      { package: pkg, change: "added", head_version: version },
      "diff.deps",
    );
    this.found.deps = deps;
    this.tl.emit(
      t + 15,
      "diff.deps",
      "diff",
      {
        evidence_id: deps.id,
        package: pkg,
        change: "added",
        base_version: null,
        head_version: version,
        source: "lockfile",
      },
      { target: { file: "pyproject.toml" }, status: "warn", parent: deps.draft },
    );
    this.log(t + 20, "diff", `dependency added: ${pkg} ${version}`, "warning");

    // Performance: one improvement, one test too fast to assess.
    t += 140;
    const daily = this.evidence(
      t,
      "diff",
      "perf_diff",
      [{ file: T.dailyRule.file, symbol: S.expandRrule.id, test: T.dailyRule.id }],
      `${T.dailyRule.id}: head/base median ratio 0.49 (95% CI 0.46–0.53), noise floor 3%`,
      { ratio: 0.49, verdict: "improvement" },
      "diff.perf",
    );
    this.found.perf = daily;
    this.tl.emit(
      t + 15,
      "diff.perf",
      "diff",
      {
        evidence_id: daily.id,
        ratio: 0.49,
        ci_low: 0.46,
        ci_high: 0.53,
        noise_floor: 0.03,
        verdict: "improvement",
        repetitions: 5,
      },
      { target: { test: T.dailyRule.id }, status: "ok", parent: daily.draft },
    );
    this.log(t + 20, "diff", "perf: test_daily_rule ×0.49 (improvement)");
    t += 120;
    const weekly = this.evidence(
      t,
      "diff",
      "perf_diff",
      [{ file: T.weeklyRule.file, test: T.weeklyRule.id }],
      `${T.weeklyRule.id}: median 1.1 ms is below the timing floor; not assessable`,
      { ratio: 1.02, verdict: "not_assessable" },
      "diff.perf",
      { stability: "n/a", origin: "n/a" },
    );
    this.tl.emit(
      t + 15,
      "diff.perf",
      "diff",
      {
        evidence_id: weekly.id,
        ratio: 1.02,
        ci_low: 0.71,
        ci_high: 1.43,
        noise_floor: 0.31,
        verdict: "not_assessable",
        repetitions: 5,
      },
      { target: { test: T.weeklyRule.id }, status: "warn", parent: weekly.draft },
    );
    this.missing(
      t + 30,
      "diff",
      "perf_not_assessable",
      [{ test: T.weeklyRule.id }],
      "Median 1.1 ms is below the timing floor.",
      "Add a benchmark with a longer workload.",
    );
    return this.stageEnd(t + 160, "diff");
  }

  private diffOutcome(at: number, test: TestSpec): number {
    const { base, head } = test.outcomes;
    const flip = test.cls === "F2P" || test.cls === "P2F";
    let summary: string;
    switch (test.cls) {
      case "new":
        summary = `${test.id}: not present on base, ${head} on head (new)`;
        break;
      case "flaky":
        summary = `${test.id}: passed on base, failed on base repeat (A′), passed on head (flaky: A and A′ disagree)`;
        break;
      case "modified":
        summary = `${test.id}: ${base} on base, ${head} on head; the test itself changed (modified)`;
        break;
      default:
        summary = `${test.id}: ${base} on base, ${head} on head (${test.cls}${flip ? `, stable over ${RERUNS + 1} runs per side` : ""})`;
    }
    const ev = this.evidence(
      at,
      "diff",
      "test_outcome",
      [{ file: test.file, test: test.id }],
      summary,
      { class: test.cls, base_outcome: base, head_outcome: head },
      "diff.outcome",
      {
        stability: test.cls === "flaky" ? "unstable" : "stable",
        origin: test.cls === "P2P" ? "n/a" : "introduced",
      },
    );
    this.outcomeEvidence.set(test, ev);
    // ADR-0015: ok = passed check, fail = flagged on its own, warn = needs a claim or not comparable.
    let status: Status = "warn";
    if (test.cls === "P2F") status = "fail";
    else if (test.cls === "P2P" || test.cls === "F2P" || test.cls === "new") status = "ok";
    const reruns = flip ? RERUNS : 0;
    this.tl.emit(
      at + 12,
      "diff.outcome",
      "diff",
      {
        evidence_id: ev.id,
        base_outcome: base,
        head_outcome: head,
        class: test.cls,
        reruns: { base: reruns, head: reruns },
      },
      { target: { test: test.id }, status, parent: ev.draft },
    );
    if (test.cls !== "P2P") {
      const level = status === "fail" ? "error" : status === "warn" ? "warning" : "info";
      this.log(at + 14, "diff", `${test.cls} ${test.id}`, level);
    }
    return at + 14;
  }

  private diffBehaviour(
    at: number,
    symbol: SymbolSpec,
    test: TestSpec,
    change: "result_changed" | "order_only",
    stability: "stable" | "unstable",
  ): EvidenceRef {
    const obs = test.observations.find((o) => o.symbol === symbol);
    if (obs === undefined) throw new Error(`${test.id} has no observation of ${symbol.id}`);
    const head = stability === "unstable" ? (obs.repeat ?? obs.head) : obs.head;
    const call = `${symbol.name}${obs.args.replace(/,\)$/, ")")}`;
    const summary =
      stability === "unstable"
        ? `${call}: result order differs between A and A′; masked as unstable`
        : `${call}: base → ${obs.base}, head → ${head} (in ${test.id})`;
    const artifact: ArtifactRef = {
      path: `obs/${symbol.module}/${symbol.name}.cbor`,
      sha256: this.rng.fork(`artifact/${symbol.id}`).hex(64),
      media_type: "application/cbor",
      size_bytes: this.rng.fork(`artifact-size/${symbol.id}`).int(400, 9000),
    };
    const ev = this.evidence(
      at,
      "diff",
      "behaviour_diff",
      [{ file: symbol.file, symbol: symbol.id, test: test.id }],
      summary,
      { change, call },
      "diff.behaviour",
      { stability, artifacts: [artifact] },
    );
    this.tl.emit(
      at + 15,
      "diff.behaviour",
      "diff",
      {
        evidence_id: ev.id,
        symbol_id: symbol.id,
        test: test.id,
        change,
        stability,
        base_preview: obs.base,
        head_preview: head,
      },
      {
        target: { file: symbol.file, symbol: symbol.id, test: test.id },
        status: "warn",
        parent: ev.draft,
      },
    );
    const note = stability === "unstable" ? " (unstable, masked)" : "";
    this.log(at + 20, "diff", `behaviour: ${symbol.name} ${change}${note}`, "warning");
    return ev;
  }

  // -------------------------------------------------------------------------------------------
  // check

  check(at: number): number {
    this.stageStart(at, "check");
    this.log(
      at + 30,
      "check",
      `evaluating ${INVARIANTS.length} invariants from repro.yml (read from base)`,
    );
    let t = at + 60;
    for (const inv of INVARIANTS) {
      t += this.jitter(260, 60);
      const ev = this.evidence(
        t,
        "check",
        "invariant",
        [{ file: "repro.yml" }],
        `Invariant ${inv.name}: ${inv.result}. ${inv.message}`,
        { invariant: inv.name, result: inv.result },
        "policy.invariants",
        { origin: "n/a" },
      );
      const deps = this.found.deps;
      const cited =
        inv.name === "no_new_dependencies" && deps !== undefined ? [ev.id, deps.id] : [ev.id];
      this.tl.emit(
        t + 15,
        "invariant.result",
        "check",
        { invariant: inv.name, result: inv.result, evidence_ids: cited, message: inv.message },
        {
          target: { file: "repro.yml" },
          status: inv.result === "pass" ? "ok" : "fail",
          parent: ev.draft,
        },
      );
      this.log(
        t + 20,
        "check",
        `${inv.name}: ${inv.result}`,
        inv.result === "pass" ? "info" : "error",
      );
    }
    return this.stageEnd(t + 120, "check");
  }

  // -------------------------------------------------------------------------------------------
  // review

  /** The evidence each claim's reviewer cites, and the exact quote it uses. */
  private citations(claim: ClaimSpec): {
    cited: EvidenceRef[];
    quote: readonly [EvidenceRef, string];
  } {
    const need = (ref: EvidenceRef | undefined, what: string): EvidenceRef => {
      if (ref === undefined) throw new Error(`no ${what} evidence for ${claim.id}`);
      return ref;
    };
    const outcome = (test: TestSpec): EvidenceRef => need(this.outcomeEvidence.get(test), test.id);
    switch (claim.id) {
      case "C1": {
        const aware = outcome(T.offsetAware);
        const cited = [
          aware,
          outcome(T.offsetNegative),
          outcome(T.springForward),
          need(this.found.parse, "parse"),
        ];
        return { cited, quote: [aware, "failed on base, passed on head"] };
      }
      case "C2": {
        const perf = need(this.found.perf, "perf");
        return { cited: [perf], quote: [perf, "head/base median ratio 0.49"] };
      }
      case "C3": {
        const fmt = need(this.found.fmt, "fmt");
        return {
          cited: [fmt, outcome(T.durationHours)],
          quote: [fmt, "base → '2h 0m', head → '2h'"],
        };
      }
      default: {
        const deps = need(this.found.deps, "deps");
        return {
          cited: [deps],
          quote: [deps, `${NEW_DEPENDENCY.package} ${NEW_DEPENDENCY.version} added`],
        };
      }
    }
  }

  private issueVerdict(
    at: number,
    claim: ClaimSpec,
    agent: AgentSpec,
    agreement: { runs: number; agreeing: number } | null,
  ): void {
    const { cited, quote } = this.citations(claim);
    if (!quote[0].summary.includes(quote[1])) {
      throw new Error(`quote for ${claim.id} is not in its evidence`);
    }
    const rationale: Record<string, string> = {
      C1: "Both offset tests flip from fail to pass, and parse_date now returns aware datetimes for offset inputs.",
      C2: "Untraced ABBA runs give a head/base median ratio of 0.49, well outside the 3% noise floor.",
      C3: "format_duration output changes for whole hours ('2h 0m' becomes '2h'), and a base test now fails on head.",
      C4: `The lockfile diff shows ${NEW_DEPENDENCY.package} added as a runtime dependency.`,
    };
    this.tl.emit(
      at,
      "verdict.issued",
      "review",
      {
        verdict: {
          claim_id: claim.id,
          verdict: claim.verdict,
          cited_evidence: cited.map((c) => c.id),
          quotes: [{ evidence_id: quote[0].id, text: quote[1] }],
          rationale: rationale[claim.id] ?? claim.text,
          model: agent.model,
          agreement,
        },
      },
      { agent: agent.id, target: claim.targets[0] ?? null, status: verdictStatus(claim) },
    );
    const agree = agreement === null ? "" : ` (${agreement.agreeing}/${agreement.runs} agree)`;
    const level = claim.verdict === "contradicted" ? "error" : "info";
    this.log(at + 10, "review", `${claim.id} ${claim.verdict}${agree}`, level);
  }

  review(at: number): number {
    this.stageStart(at, "review");
    this.log(at + 30, "review", `judging ${CLAIMS.length} claims against cited evidence`);
    const ends = CLAIMS.map((claim, i) => {
      const agent = AGENTS.reviewers[i];
      if (agent === undefined) throw new Error(`no reviewer for ${claim.id}`);
      return this.reviewer(at + 120 + i * 180, claim, agent);
    });

    // The gap reviewer maps every difference to the claims that explain it, after the verdicts.
    const gap = this.gapItems();
    const gapEnd = this.script(Math.max(...ends) + 200, "review", AGENTS.gap, [
      { after: 60, state: "thinking", detail: "gap = list_gap(run)", progress: 0.05 },
      ...gap.map(
        (item, i): ScriptStep => ({
          after: this.jitter(420, 120),
          state: "tool_call",
          tool: "mcp__repro__explain",
          detail: `explain("${item.ref.id}", ${item.by ?? "None"})`,
          progress: round(0.1 + (0.8 * (i + 1)) / gap.length, 2),
        }),
      ),
      {
        after: 300,
        state: "done",
        detail: `${gap.filter((g) => g.by !== null).length} explained · ${gap.filter((g) => g.by === null).length} unexplained`,
        progress: 1,
      },
    ]);
    this.cost(gapEnd + 5, "review", AGENTS.gap);

    const qaEnd = this.script(gapEnd + 120, "review", AGENTS.qa, [
      { after: 60, state: "thinking", detail: "card = draft_card(run)", progress: 0.2 },
      {
        after: this.jitter(1100, 200),
        state: "tool_call",
        tool: "mcp__repro__check_consistency",
        detail: "check_consistency(card)",
        progress: 0.6,
      },
      {
        after: this.jitter(900, 200),
        state: "tool_call",
        tool: "mcp__repro__list_missing",
        detail: "missing = list_missing(run)",
        progress: 0.85,
      },
      {
        after: this.jitter(700, 150),
        state: "done",
        detail: "consistent: verdicts match evidence",
        progress: 1,
      },
    ]);
    this.cost(qaEnd + 5, "review", AGENTS.qa);
    return this.stageEnd(qaEnd + 100, "review");
  }

  /** One reviewer agent judging one claim; returns when it is done. */
  private reviewer(start: number, claim: ClaimSpec, agent: AgentSpec): number {
    const { cited, quote } = this.citations(claim);
    const getEvidence = (from: number, span: number): ScriptStep[] =>
      cited.map((ref, i) => ({
        after: this.jitter(800, 250),
        state: "tool_call",
        tool: "mcp__repro__get_evidence",
        detail: `get_evidence("${ref.id}")`,
        progress: round(from + (span * (i + 1)) / cited.length, 2),
      }));
    const steps: ScriptStep[] = [
      { after: 60, state: "thinking", detail: `ev = evidence_for(${claim.id})`, progress: 0.1 },
      ...getEvidence(0.15, 0.4),
    ];
    if (claim.id === "C2") {
      // The first attempt quotes the PR's wording instead of the evidence and is rejected.
      steps.push(
        {
          after: this.jitter(1300, 200),
          state: "thinking",
          detail: `verdict(${claim.id}) = supported`,
          progress: 0.6,
        },
        {
          after: 300,
          state: "thinking",
          detail: "rejected: quote not found in evidence; retrying",
          progress: 0.65,
          also: (t) => {
            this.tl.emit(
              t,
              "verdict.rejected",
              "review",
              {
                claim_id: claim.id,
                reason: "quote_mismatch",
                detail: `Quote "about twice as fast" is not an exact substring of ${quote[0].id}.`,
              },
              { agent: agent.id, status: "warn" },
            );
            this.log(
              t + 5,
              "review",
              `${claim.id} verdict rejected: quote mismatch, retrying`,
              "warning",
            );
          },
        },
        {
          after: this.jitter(900, 200),
          state: "tool_call",
          tool: "mcp__repro__get_evidence",
          detail: `get_evidence("${quote[0].id}")`,
          progress: 0.75,
        },
      );
    }
    steps.push({
      after: this.jitter(700, 150),
      state: "tool_call",
      tool: "mcp__repro__quote",
      detail: `quote("${quote[0].id}", "${quote[1]}")`,
      progress: 0.8,
    });
    if (claim.verdict === "contradicted") {
      // A contradicted verdict needs an order-swapped second pass that agrees (ARCHITECTURE §10.4).
      const swap = AGENTS.swap;
      steps.push({
        after: this.jitter(900, 150),
        state: "waiting",
        detail: `order_swap(${claim.id}) → ${swap.id}`,
        progress: 0.85,
        also: (t) => {
          const end = this.script(t + 20, "review", swap, [
            {
              after: 50,
              state: "thinking",
              detail: `ev = evidence_for(${claim.id}, order="swapped")`,
              progress: 0.2,
            },
            ...cited.map(
              (ref, i): ScriptStep => ({
                after: this.jitter(700, 150),
                state: "tool_call",
                tool: "mcp__repro__get_evidence",
                detail: `get_evidence("${ref.id}")`,
                progress: round(0.3 + (0.5 * (i + 1)) / cited.length, 2),
              }),
            ),
            {
              after: this.jitter(800, 150),
              state: "done",
              detail: `${claim.id}: contradicted (agrees)`,
              progress: 1,
            },
          ]);
          this.cost(end + 5, "review", swap);
          this.swapEnd = end + 5;
        },
      });
    }
    let end = this.script(start, "review", agent, [
      ...steps,
      {
        after: this.jitter(900, 200),
        state: "thinking",
        detail: `verdict(${claim.id}) = ${claim.verdict}`,
        progress: 0.9,
      },
    ]);
    if (claim.verdict === "contradicted") end = Math.max(end, this.swapEnd + 60);
    const agreement = claim.verdict === "contradicted" ? { runs: 2, agreeing: 2 } : null;
    this.issueVerdict(end + 20, claim, agent, agreement);
    this.agentState(end + 60, "review", agent, {
      state: "done",
      detail: `${claim.id}: ${claim.verdict}`,
      progress: 1,
    });
    this.cost(end + 65, "review", agent);
    return end + 65;
  }

  /** Differences that belong on the card's gap list, each with the supported claim explaining it. */
  private gapItems(): GapItem[] {
    const explainedBy = new Map<string, string>();
    for (const claim of CLAIMS) {
      if (claim.verdict !== "supported") continue;
      for (const ref of this.citations(claim).cited) explainedBy.set(ref.id, claim.id);
    }
    const refs: EvidenceRef[] = [];
    for (const test of this.repo.tests) {
      if (test.cls === "P2P" || test.cls === "flaky") continue;
      const ref = this.outcomeEvidence.get(test);
      if (ref !== undefined) refs.push(ref);
    }
    for (const ref of [
      this.found.tamper,
      this.found.parse,
      this.found.fmt,
      this.found.deps,
      this.found.perf,
    ]) {
      if (ref !== undefined) refs.push(ref);
    }
    return refs.map((ref) => ({ ref, by: explainedBy.get(ref.id) ?? null }));
  }

  // -------------------------------------------------------------------------------------------
  // card

  card(at: number): { end: number; card: CardPublishedPayload } {
    this.stageStart(at, "card");
    const gap = this.gapItems();
    const card: CardPublishedPayload = {
      status: "FLAGGED",
      card_sha256: this.rng.fork("card").hex(64),
      counts: {
        claims: CLAIMS.length,
        supported: CLAIMS.filter((c) => c.verdict === "supported").length,
        contradicted: CLAIMS.filter((c) => c.verdict === "contradicted").length,
        unverifiable: CLAIMS.filter((c) => c.verdict === "unverifiable").length,
        gap_items: gap.length,
        unexplained: gap.filter((g) => g.by === null).length,
        missing: this.missingCount,
        invariants_failed: INVARIANTS.filter((i) => i.result === "fail").length,
      },
    };
    this.tl.emit(at + 400, "card.published", "card", card, { status: "fail" });
    const c = card.counts;
    this.log(
      at + 420,
      "card",
      `card FLAGGED · ${c.supported} supported · ${c.contradicted} contradicted · ${c.unexplained} unexplained · ${c.missing} missing`,
      "error",
    );
    return { end: this.stageEnd(at + 520, "card"), card };
  }

  finish(at: number, card: CardPublishedPayload): void {
    this.tl.emit(
      at,
      "run.finished",
      "card",
      {
        outcome: "completed",
        card_status: card.status,
        duration_ms: at,
        counts: {
          events: this.tl.size + 1,
          evidence: this.tl.count((d) => d.kind === "evidence.created"),
          missing: this.missingCount,
        },
      },
      { status: "ok" },
    );
  }
}

/** Number of checks in each final class, from the story's plan (ADR-0015). */
function plannedChecks(
  tests: readonly TestSpec[],
): Pick<RunSummary, "checks" | "passed" | "flagged" | "unassessed"> {
  // Outcome checks: P2P/F2P/new pass, P2F flags, flaky/modified cannot be assessed.
  const outcome = { passed: 0, flagged: 0, unassessed: 0 };
  for (const test of tests) {
    if (test.cls === "P2F") outcome.flagged++;
    else if (test.cls === "flaky" || test.cls === "modified") outcome.unassessed++;
    else outcome.passed++;
  }
  // Story checks beyond outcomes: test tampering (flag); behaviour parse (explained by C1),
  // fmt (contradicted by C3), expand_rrule (unstable); deps (explained by C4); perf daily
  // (improvement), weekly (not assessable); invariants (3 pass, 1 fail).
  const passed = outcome.passed + 1 + 1 + 1 + 3;
  const flagged = outcome.flagged + 1 + 1 + 1;
  const unassessed = outcome.unassessed + 1 + 1;
  return { checks: passed + flagged + unassessed, passed, flagged, unassessed };
}

/**
 * Generates a complete synthetic run. The same profile and seed always give the same events,
 * byte for byte once serialised with `toJsonl`.
 */
export function generateRun(profile: Profile, seed: number): SyntheticRun {
  const run = new RunBuilder(profile, seed);
  let t = run.read(0);
  t = run.build(t + 100);
  t = run.run(t + 100);
  t = run.diff(t + 100);
  t = run.check(t + 100);
  t = run.review(t + 100);
  const { end, card } = run.card(t + 100);
  run.finish(end + 40, card);

  const events = run.tl.build({
    startMs: RUN_START_MS,
    runId: run.runId,
    producer: PRODUCER,
    ids: new Rng(seed).fork("event-ids"),
  });
  for (const event of events) {
    if (event.kind === "evidence.created") event.payload.evidence.seq = event.seq;
  }

  const summary: RunSummary = {
    events: events.length,
    claims: CLAIMS.length,
    agents: 1 + AGENTS.probes.length + AGENTS.reviewers.length + 3,
    files: run.repo.modules.length,
    graphNodes: run.graphNodeCount(),
    graphEdges: run.repo.imports.length + run.repo.coverEdges.length + run.repo.callEdges.length,
    selectedTests: run.repo.tests.length,
    ...plannedChecks(run.repo.tests),
    evidence: events.filter((e) => e.kind === "evidence.created").length,
    missing: run.missingItems,
    card,
    durationMs: end + 40,
  };
  return { profile, seed, events, summary };
}
