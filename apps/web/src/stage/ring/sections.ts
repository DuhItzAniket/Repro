/**
 * Sections of the wheel (B14): every event belongs to the section of its file's ring card. A
 * bunch of strands hits its section from inside, and the section answers with lines outside the
 * wheel, from that same section, turning with it, like the reference's. An event whose file has
 * no card has no section, and draws nothing outside the wheel.
 *
 * Angles here are ring-local (before the ring's rotation), so a layer that draws in this frame
 * turns with the ring through its `rotation`, and a section stays the same section.
 */
import type { ReproEvent } from "@repro/events";
import type { CockpitModel } from "../../model/cockpit";
import { targetFile } from "./content";
import type { RingModel } from "./layers";

const UNIT = 4294967296;
/** Share of a card's span a section's lines spread across (centred). */
const SPAN = 0.8;

/** The symbol an event is about: a trace's function, else its target's symbol. */
export function eventSymbol(event: ReproEvent): string | undefined {
  if (event.kind === "trace.sample" || event.kind === "diff.behaviour")
    return event.payload.symbol_id;
  return event.target?.symbol ?? undefined;
}

/** The file an event is about: its symbol's own file, else its target's file. */
export function eventFile(model: CockpitModel, event: ReproEvent): string | undefined {
  const symbol = eventSymbol(event);
  if (symbol !== undefined) {
    const node = model.graph.nodeForSymbol(symbol);
    if (node !== undefined) return model.graph.files[node];
  }
  return targetFile(event.target);
}

/** The ring-local angle of a card's centre. */
export function cardCentre(ring: RingModel, card: number): number {
  return ((ring.angles.start[card] as number) + (ring.angles.end[card] as number)) / 2;
}

/**
 * The ring-local angle an event's line takes within its file's section: spread across the card
 * by `h` (a 32-bit hash, so the same event always takes the same place). NaN when the file has
 * no card.
 */
export function sectionAngle(ring: RingModel, file: string | undefined, h: number): number {
  const card = file === undefined ? undefined : ring.cardOf.get(file);
  if (card === undefined) return Number.NaN;
  const start = ring.angles.start[card] as number;
  const end = ring.angles.end[card] as number;
  return start + (end - start) * ((1 - SPAN) / 2 + SPAN * (h / UNIT));
}
