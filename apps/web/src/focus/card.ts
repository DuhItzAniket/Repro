/**
 * The Reproduction Card in the drawer (F05; ARCHITECTURE §7, DESIGN.md "Accessibility": the card
 * is a semantic table). A pure function of the run's `card.published` payload: the engine
 * assembled the card from the run's own log, so the cockpit shows it as published, and each gap
 * item links to the check that reported it.
 */
import type { CardPublishedPayload, ReproductionCard } from "@repro/events";
import type { DrawerRow, DrawerSection, DrawerView } from "./evidence";
import type { Focus } from "./focus";

const NONE = "—";

/** What each status means, in a line. */
export const STATUS_LINE: Readonly<Record<ReproductionCard["status"], string>> = {
  VERIFIED: "every claim supported, no difference unexplained, every invariant holding",
  FLAGGED: "the run found a problem",
  UNVERIFIABLE: "something could not be checked",
};

const value = (v: string | number | null | undefined): string =>
  v === null || v === undefined || v === "" ? NONE : String(v);

/** A check that reports `evidenceId`, by its index in the checks projection. */
export type CheckOf = (evidenceId: string) => number | null;

function reasons(card: ReproductionCard): DrawerSection[] {
  const rows = (decides: boolean) =>
    card.status_reasons
      .filter((r) => r.decides === decides)
      .map((r) => `${r.detail} (${r.rule.replaceAll("_", " ")})`);
  const why = rows(true);
  const also = rows(false);
  return [
    {
      title: "Why",
      paragraphs: why.length > 0 ? why : ["Nothing flags, and everything was checked."],
    },
    ...(also.length > 0 ? [{ title: "Also not checked", paragraphs: also }] : []),
  ];
}

/** A gap item's result, with what is unusual about it (most items are introduced and stable). */
function resultOf(item: ReproductionCard["gap"][number]): string {
  const notes = [
    ...(item.explained_by.length > 0 ? [`by ${item.explained_by.join(", ")}`] : []),
    ...(item.origin === "pre-existing" ? ["pre-existing"] : []),
    ...(item.stability === "unstable" ? ["unstable"] : []),
  ];
  return notes.length > 0 ? `${item.resolution} (${notes.join(", ")})` : item.resolution;
}

function gap(card: ReproductionCard, checkOf: CheckOf): DrawerSection {
  const rows: DrawerRow[] = card.gap.map((item) => {
    const index = checkOf(item.evidence_id);
    const focus: Focus | undefined = index === null ? undefined : { kind: "check", index };
    return {
      cells: [`${item.check} ${item.kind}`, `${resultOf(item)}: ${item.summary}`],
      ...(focus === undefined ? {} : { focus }),
    };
  });
  return {
    title: "Gap",
    table: {
      caption: "Differences the run found, and what the status rules made of each",
      columns: ["Difference", "Result"],
      rows,
    },
  };
}

function conditions(card: ReproductionCard): DrawerSection {
  const c = card.conditions;
  return {
    title: "Conditions",
    facts: [
      { label: "Base", value: `${c.base.ref} (${c.base.sha.slice(0, 12)})` },
      { label: "Head", value: `${c.head.ref} (${c.head.sha.slice(0, 12)})` },
      { label: "Python", value: value(c.python_version) },
      { label: "Platform", value: value(c.platform) },
      { label: "Isolation", value: value(c.isolation_level) },
      { label: "Network", value: value(c.network) },
      { label: "Lock, base", value: value(c.lock_sha256.base) },
      { label: "Lock, head", value: value(c.lock_sha256.head) },
      { label: "Selected tests", value: String(c.selected_tests) },
      {
        label: "Hash seeds (A, A2)",
        value: c.seeds === null ? NONE : `${c.seeds.hash_seed}, ${c.seeds.hash_seed_repeat}`,
      },
      { label: "Repro", value: c.repro_version },
      { label: "Models", value: c.models.join(", ") || NONE },
    ],
  };
}

/** The drawer for the card, or what is known before it is published. */
export function cardView(payload: CardPublishedPayload | null, checkOf: CheckOf): DrawerView {
  if (payload === null)
    return { title: "Reproduction Card", subtitle: "not published yet", sections: [] };
  const counts = payload.counts;
  const summary: DrawerSection = {
    title: "Status",
    facts: [
      { label: "Status", value: payload.status },
      { label: "Gap items", value: String(counts.gap_items) },
      { label: "Unexplained", value: String(counts.unexplained) },
      { label: "Invariants failed", value: String(counts.invariants_failed) },
      { label: "Missing items", value: String(counts.missing) },
      {
        label: "Claims",
        value: `${counts.claims}: ${counts.supported} supported, ${counts.contradicted} contradicted, ${counts.unverifiable} unverifiable`,
      },
      { label: "Card SHA-256", value: payload.card_sha256 },
    ],
  };
  const title = `Reproduction Card · ${payload.status}`;
  const card = payload.card;
  if (card === undefined)
    return {
      title,
      subtitle: STATUS_LINE[payload.status],
      sections: [
        summary,
        {
          title: "Card",
          paragraphs: ["This log's card.published carries no card, only its status and counts."],
        },
      ],
    };
  const verdicts = new Map(card.verdicts.map((v) => [v.claim_id, v.verdict]));
  return {
    title,
    subtitle: STATUS_LINE[card.status],
    sections: [
      summary,
      ...reasons(card),
      {
        title: "Claims",
        table: {
          caption: "The claims and their verdicts",
          columns: ["Claim", "Verdict"],
          rows: card.claims.map((claim) => ({
            cells: [claim.id, `${verdicts.get(claim.id) ?? "not judged"}: ${claim.text}`],
            focus: { kind: "claim", id: claim.id },
          })),
        },
      },
      gap(card, checkOf),
      {
        title: "Invariants",
        table: {
          caption: "Each invariant base's repro.yml declares",
          columns: ["Invariant", "Result"],
          rows: card.invariants.map((i) => ({ cells: [i.name, `${i.result}: ${i.message}`] })),
        },
      },
      {
        title: "Missing",
        table: {
          caption: "What could not be checked, and why (each detail names its targets)",
          columns: ["Reason", "Detail"],
          rows: card.missing.map((m) => ({ cells: [m.reason, m.detail] })),
        },
      },
      conditions(card),
      {
        title: "Replay",
        paragraphs: [
          `repro replay ${card.run_id} assembles this card again from its ${card.replay.event_count} events.`,
          `Log SHA-256 ${card.replay.event_log_sha256}; generated at ${card.generated_at}.`,
        ],
      },
    ],
  };
}
