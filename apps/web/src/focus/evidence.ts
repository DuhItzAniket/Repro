/**
 * The evidence drawer's content (DESIGN.md "Panels": a side drawer with the evidence, "raw diff,
 * trace samples, verdict text"). A pure function of (focus, events up to the cursor): it shows
 * what the log says about the focused claim, check, file, symbol or agent, quoting evidence
 * summaries and data, verdict rationales and quotes, and trace samples as recorded; or the
 * run's Reproduction Card, once published (F05, `./card`).
 */
import type { ReproEvent } from "@repro/events";
import { nameOf } from "../model/changes";
import { basename, checkIndex, relates, routeTests, type Scope } from "../model/check-index";
import type { CockpitModel, CockpitState } from "../model/cockpit";
import { cardView } from "./card";
import type { Focus } from "./focus";

export interface Fact {
  readonly label: string;
  readonly value: string;
}

export interface DrawerRow {
  readonly cells: readonly string[];
  /** Focus this row's first cell links to. */
  readonly focus?: Focus;
}

export interface DrawerTable {
  readonly caption: string;
  readonly columns: readonly string[];
  readonly rows: readonly DrawerRow[];
}

export interface DrawerSection {
  readonly title: string;
  readonly facts?: readonly Fact[];
  readonly paragraphs?: readonly string[];
  readonly table?: DrawerTable;
}

/** What a focus shows. */
export interface DrawerContent {
  readonly title: string;
  readonly subtitle: string;
  readonly sections: readonly DrawerSection[];
}

export interface DrawerView extends DrawerContent {
  /**
   * Whether the events up to the cursor are all there will be: the run has finished, or this is
   * its published card. An empty table then says "None.", and "None yet." while more can come.
   */
  readonly final: boolean;
}

/** A payload value as text: scalars as they are, small structures as compact JSON. */
const text = (value: unknown): string =>
  value === null || value === undefined
    ? "—"
    : typeof value === "object"
      ? JSON.stringify(value)
      : String(value);

const lines = (range: readonly number[] | null): string =>
  range === null ? "—" : `${range[0]}–${range[1]}`;

function eventsOf<K extends ReproEvent["kind"]>(
  model: CockpitModel,
  kind: K,
  cursor: number,
): Extract<ReproEvent, { kind: K }>[] {
  const out: Extract<ReproEvent, { kind: K }>[] = [];
  for (const i of model.kinds.last(kind, cursor, Number.MAX_SAFE_INTEGER)) {
    const event = model.store.event(i);
    if (event?.kind === kind) out.push(event as Extract<ReproEvent, { kind: K }>);
  }
  return out;
}

/** The checks related to `scope`, as a table that links to each check. */
function checksTable(
  model: CockpitModel,
  cursor: number,
  scope: Scope,
  caption: string,
): DrawerTable {
  const { list } = model.folder.stateAt(cursor).checks;
  const rows: DrawerRow[] = [];
  list.forEach((check, index) => {
    if (!relates(scope, check.target, check.evidence)) return;
    const target = check.target?.symbol ?? check.target?.test ?? check.target?.file ?? "—";
    rows.push({
      cells: [`#${index + 1} ${check.kind}`, target, check.result],
      focus: { kind: "check", index },
    });
  });
  return { caption, columns: ["Check", "Target", "Result"], rows };
}

const scopeOf = (
  files: Iterable<string>,
  symbols: Iterable<string>,
  tests: Iterable<string>,
  cited: Iterable<string> = [],
): Scope => ({
  files: new Set(files),
  symbols: new Set(symbols),
  tests: new Set(tests),
  cited: new Set(cited),
});

/** Tests routed to any of `symbols` (by `ChangeIndex`). */
function testsFor(model: CockpitModel, cursor: number, symbols: ReadonlySet<string>): string[] {
  const testsOf = routeTests(model.changes, cursor);
  const tests = new Set<string>();
  model.changes.changed.forEach((change, c) => {
    if (change.index < cursor && symbols.has(change.symbol))
      for (const test of testsOf.get(c) ?? []) tests.add(test);
  });
  return [...tests].sort();
}

export function drawerView(focus: Focus, model: CockpitModel, cursor: number): DrawerView {
  const state = model.folder.stateAt(cursor);
  const { run } = state;
  const final = run.finishedAt !== null || (focus.kind === "card" && run.card !== null);
  return { ...contentOf(focus, model, cursor, state), final };
}

function contentOf(
  focus: Focus,
  model: CockpitModel,
  cursor: number,
  state: CockpitState,
): DrawerContent {
  switch (focus.kind) {
    case "claim": {
      const claim = state.claims.list[state.claims.byId.get(focus.id) ?? -1];
      if (claim === undefined)
        return { title: focus.id, subtitle: "not extracted yet", sections: [] };
      const verdict = eventsOf(model, "verdict.issued", cursor)
        .filter((e) => e.payload.verdict.claim_id === claim.id)
        .at(-1)?.payload.verdict;
      const row = checkIndex(state, model.changes, cursor).rows.find((r) => r.id === claim.id);
      const symbols = claim.targets.flatMap((t) => (t.symbol === undefined ? [] : [t.symbol]));
      const files = claim.targets.flatMap((t) => (t.file === undefined ? [] : [t.file]));
      const scope = scopeOf(files, symbols, testsFor(model, cursor, new Set(symbols)), claim.cited);
      return {
        title: `${claim.id} · ${claim.kind}`,
        subtitle: claim.text,
        sections: [
          {
            title: "Verdict",
            facts: [
              { label: "Verdict", value: claim.verdict ?? "pending review" },
              { label: "Status in the index", value: row?.status ?? "review" },
              {
                label: "Agreement",
                value:
                  claim.agreement === null
                    ? "—"
                    : `${claim.agreement.agreeing} of ${claim.agreement.runs} runs agree`,
              },
              { label: "Reviewer", value: claim.agent ?? "—" },
              { label: "Model", value: verdict?.model ?? "—" },
              { label: "Rejected attempts", value: String(claim.rejections) },
              {
                label: "Targets",
                value: claim.targets.map((t) => t.symbol ?? t.file ?? t.test ?? "").join(", "),
              },
            ],
            paragraphs: [
              ...(verdict === undefined ? [] : [verdict.rationale]),
              ...(verdict?.quotes ?? []).map((q) => `“${q.text}” (${q.evidence_id})`),
            ],
          },
          {
            title: "Related checks",
            table: checksTable(model, cursor, scope, `Checks related to ${claim.id}`),
          },
        ],
      };
    }
    case "check": {
      const check = state.checks.list[focus.index];
      if (check === undefined)
        return { title: `Check #${focus.index + 1}`, subtitle: "not run yet", sections: [] };
      const event = model.store.event(check.seq - 1); // a gap-free store: index = seq - 1
      const evidence = eventsOf(model, "evidence.created", cursor)
        .map((e) => e.payload.evidence)
        .filter((e) => check.evidence.includes(e.id));
      const payload: object = event === null ? {} : event.payload;
      const sections: DrawerSection[] = [
        {
          title: "Result",
          facts: [
            { label: "Result", value: check.result },
            { label: "Status", value: event?.status ?? "—" },
            { label: "Target", value: text(check.target) },
            ...Object.entries(payload)
              .filter(([key]) => key !== "evidence_id" && key !== "evidence_ids")
              .map(([label, value]) => ({ label, value: text(value) })),
          ],
        },
        ...evidence.map((item) => ({
          title: `Evidence ${item.id}`,
          paragraphs: [item.summary],
          facts: [
            { label: "Type", value: item.type },
            { label: "Stability", value: item.stability },
            { label: "Origin", value: item.origin },
            ...Object.entries(item.data).map(([label, value]) => ({ label, value: text(value) })),
          ],
        })),
      ];
      if (event?.kind === "diff.behaviour") {
        const cell = model.observations.cellOf(event.payload.test, event.payload.symbol_id);
        const rows: DrawerRow[] = model.observations.samples
          .filter((s) => s.cell === cell && s.index < cursor)
          .map((s) => ({
            cells: [
              String(s.call),
              s.side,
              s.raised === null ? text(s.result) : `raises ${s.raised}`,
            ],
          }));
        sections.push({
          title: "Trace samples",
          table: { caption: "Recorded calls", columns: ["Call", "Side", "Result"], rows },
        });
      }
      const citing = state.claims.list.filter((c) =>
        c.cited.some((id) => check.evidence.includes(id)),
      );
      if (citing.length > 0)
        sections.push({
          title: "Cited by",
          table: {
            caption: "Claims whose verdict cites this evidence",
            columns: ["Claim", "Verdict"],
            rows: citing.map((c) => ({
              cells: [c.id, c.verdict ?? "—"],
              focus: { kind: "claim", id: c.id },
            })),
          },
        });
      return {
        title: `Check #${focus.index + 1} · ${check.kind}`,
        subtitle: evidence[0]?.summary ?? text(check.target),
        sections,
      };
    }
    case "file":
    case "symbol": {
      const changes = eventsOf(model, "symbol.changed", cursor).filter((e) =>
        focus.kind === "file"
          ? e.payload.file === focus.file
          : e.payload.symbol_id === focus.symbol,
      );
      const symbols = new Set(
        focus.kind === "symbol" ? [focus.symbol] : changes.map((e) => e.payload.symbol_id),
      );
      const tests = testsFor(model, cursor, symbols);
      const scope = scopeOf(focus.kind === "file" ? [focus.file] : [], symbols, tests);
      return {
        title: focus.kind === "file" ? basename(focus.file) : nameOf(focus.symbol),
        subtitle: focus.kind === "file" ? focus.file : focus.symbol,
        sections: [
          {
            title: "Changes",
            table: {
              caption: "Changed symbols (base and head line ranges)",
              columns: ["Symbol", "Change", "Base lines", "Head lines"],
              rows: changes.map((e) => ({
                cells: [
                  nameOf(e.payload.symbol_id),
                  e.payload.change,
                  lines(e.payload.base_lines),
                  lines(e.payload.head_lines),
                ],
                focus: { kind: "symbol", symbol: e.payload.symbol_id, file: e.payload.file },
              })),
            },
          },
          {
            title: "Routed tests",
            paragraphs: tests.length === 0 ? ["No selected test reaches it."] : tests,
          },
          { title: "Related checks", table: checksTable(model, cursor, scope, "Related checks") },
        ],
      };
    }
    case "agent": {
      const agent = state.agents.byId.get(focus.id);
      if (agent === undefined)
        return { title: focus.id, subtitle: "not spawned yet", sections: [] };
      const { supported, contradicted, unverifiable } = agent.verdicts;
      return {
        title: `${agent.id} · ${agent.role}`,
        subtitle: agent.model,
        sections: [
          {
            title: "State",
            facts: [
              { label: "State", value: agent.state },
              { label: "Progress", value: `${Math.round(agent.progress * 100)}%` },
              { label: "Tool", value: agent.tool ?? "—" },
              {
                label: "Verdicts",
                value: `${supported} supported, ${contradicted} contradicted, ${unverifiable} unverifiable`,
              },
              { label: "Rejected verdicts", value: String(agent.rejected) },
            ],
          },
          { title: "Recent tool calls", paragraphs: agent.recent.map((line) => line.text) },
        ],
      };
    }
    case "card": {
      const checks = state.checks.list;
      return cardView(state.run.card, (evidenceId) => {
        const index = checks.findIndex((check) => check.evidence.includes(evidenceId));
        return index < 0 ? null : index;
      });
    }
  }
}
