/**
 * The change×check index (DESIGN.md panel 8, ADR-0015): rows are claims, then changes no claim
 * covers (grouped by file), then the checks that relate to neither; columns are the checks
 * themselves, in arrival order. A column's result is the check's result from the checks
 * projection, so the matrix, the index footer and the header's CHECKS / FLAGGED counters all read
 * one list.
 *
 * A claim covers the symbols it targets; a target with a file and no symbol covers every change
 * in that file. A check that names a symbol relates to the rows covering that symbol. Any other
 * check relates to a row when it targets one of the row's files, or a test that routes to one
 * of the row's symbols (`ChangeIndex`). A claim also relates to every check whose evidence its
 * verdict cites.
 */
import type { Target } from "@repro/events";
import { type ChangeIndex, nameOf } from "./changes";
import type { CockpitState } from "./cockpit";
import type { CheckResult } from "./projections/checks";

export type RowStatus = "verified" | "flagged" | "review";

export interface IndexRow {
  /** Claim id, file path, or `other`. */
  readonly id: string;
  readonly label: string;
  readonly kind: "claim" | "change" | "other";
  /** Indices into `results` of the checks related to this row, ascending. */
  readonly checks: readonly number[];
  readonly status: RowStatus;
}

export interface CheckIndexView {
  /** One result per check, in arrival order (the columns). */
  readonly results: readonly CheckResult[];
  readonly rows: readonly IndexRow[];
}

/** What a row (or a change route) covers. */
export interface Scope {
  readonly files: ReadonlySet<string>;
  readonly symbols: ReadonlySet<string>;
  readonly tests: ReadonlySet<string>;
  readonly cited: ReadonlySet<string>;
}

/** Whether a check with this target and evidence bears on `scope`. */
export function relates(scope: Scope, target: Target | null, evidence: readonly string[]): boolean {
  if (evidence.some((id) => scope.cited.has(id))) return true;
  if (target === null) return false;
  // A check that names a symbol is evidence about that symbol only.
  if (target.symbol !== undefined) return scope.symbols.has(target.symbol);
  if (target.file !== undefined && scope.files.has(target.file)) return true;
  return target.test !== undefined && scope.tests.has(target.test);
}

export const basename = (path: string): string => path.slice(path.lastIndexOf("/") + 1);

/** Selected tests per changed symbol (index into `changes.changed`), as of `cursor`. */
export function routeTests(changes: ChangeIndex, cursor: number): Map<number, Set<string>> {
  const testsOf = new Map<number, Set<string>>();
  changes.selections.forEach((selection, s) => {
    if (selection.index >= cursor) return;
    for (const c of changes.routesOf(s)) {
      const set = testsOf.get(c);
      if (set === undefined) testsOf.set(c, new Set([selection.test]));
      else set.add(selection.test);
    }
  });
  return testsOf;
}

/** The index as of `cursor`; `state` must be the cockpit state folded to the same cursor. */
export function checkIndex(
  state: CockpitState,
  changes: ChangeIndex,
  cursor: number,
): CheckIndexView {
  const checks = state.checks.list;
  const results = checks.map((c) => c.result);
  const changed = changes.changed.filter((c) => c.index < cursor);

  const testsOf = routeTests(changes, cursor);
  const scopeOf = (files: Set<string>, symbols: Set<string>, cited: Iterable<string>): Scope => {
    const tests = new Set<string>();
    changes.changed.forEach((c, i) => {
      if (c.index >= cursor || !symbols.has(c.symbol)) return;
      for (const test of testsOf.get(i) ?? []) tests.add(test);
    });
    return { files, symbols, tests, cited: new Set(cited) };
  };

  const rows: IndexRow[] = [];
  const related = new Uint8Array(checks.length);
  const rowChecks = (scope: Scope): number[] => {
    const out: number[] = [];
    checks.forEach((check, i) => {
      if (!relates(scope, check.target, check.evidence)) return;
      out.push(i);
      related[i] = 1;
    });
    return out;
  };
  const any = (list: readonly number[], result: CheckResult) =>
    list.some((i) => results[i] === result);

  const claimedFiles = new Set<string>();
  const claimedSymbols = new Set<string>();
  for (const claim of state.claims.list) {
    const files = new Set<string>();
    const symbols = new Set<string>();
    for (const target of claim.targets) {
      if (target.file !== undefined) files.add(target.file);
      if (target.symbol !== undefined) symbols.add(target.symbol);
      // A file-only target claims every change in that file.
      if (target.symbol === undefined && target.file !== undefined)
        for (const c of changed) if (c.file === target.file) symbols.add(c.symbol);
    }
    for (const file of files) claimedFiles.add(file);
    for (const symbol of symbols) claimedSymbols.add(symbol);
    const list = rowChecks(scopeOf(files, symbols, claim.cited));
    const status: RowStatus =
      claim.verdict === "contradicted" || any(list, "flagged")
        ? "flagged"
        : claim.verdict === "supported" && !any(list, "pending")
          ? "verified"
          : "review";
    rows.push({
      id: claim.id,
      label: `${claim.id} ${claim.kind}`,
      kind: "claim",
      checks: list,
      status,
    });
  }

  // Changes no claim covers, grouped by file in the order they changed.
  const unclaimed = new Map<string, Set<string>>();
  for (const c of changed) {
    if (claimedSymbols.has(c.symbol)) continue;
    const symbols = unclaimed.get(c.file);
    if (symbols === undefined) unclaimed.set(c.file, new Set([c.symbol]));
    else symbols.add(c.symbol);
  }
  for (const [file, symbols] of unclaimed) {
    // Symbol-less checks on the file belong to a claim if one targets the file.
    const files = claimedFiles.has(file) ? new Set<string>() : new Set([file]);
    const list = rowChecks(scopeOf(files, symbols, []));
    const only = symbols.size === 1 ? ([...symbols][0] as string) : null;
    rows.push({
      id: file,
      label:
        only !== null && !only.includes(":<module>#")
          ? nameOf(only)
          : `${basename(file)}${symbols.size > 1 ? ` ×${symbols.size}` : ""}`,
      kind: "change",
      checks: list,
      // No claim explains this change, so it is never "verified" here.
      status: any(list, "flagged") ? "flagged" : "review",
    });
  }

  const rest: number[] = [];
  for (let i = 0; i < checks.length; i++) if (related[i] !== 1) rest.push(i);
  if (rest.length > 0)
    rows.push({
      id: "other",
      label: "other",
      kind: "other",
      checks: rest,
      status: any(rest, "flagged") ? "flagged" : any(rest, "pending") ? "review" : "verified",
    });
  return { results, rows };
}
