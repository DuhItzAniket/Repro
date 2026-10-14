/**
 * The stage's look (B15): per-viewer settings for how thick and how bright each kind of line is,
 * and how much of the wheel the stage shows. They change only how things are drawn, never which
 * events draw: the layers write the same instances whatever the look, and the shader scales
 * widths and alphas by uniforms (`StageHost`). The flash governor reads the widths of the
 * elements it counts, so its bound holds at every setting.
 *
 * Flash safety by range: the dim strands and the lines outside the wheel are not counted by the
 * governor, because they are MAX-blended at no more than `DIM_MAX`. Their brightness can only be
 * turned down from that ceiling. The counted elements (bullets, mesh flares) may be made brighter
 * or wider: the governor counts their area, whatever their intensity, at the width chosen here.
 */

/** The parts of the stage a viewer can restyle. */
export const LOOK_PARTS = ["strands", "bullets", "mesh", "nodes", "lines"] as const;
export type LookPart = (typeof LOOK_PARTS)[number];

export interface PartLook {
  /** Line width, as a multiple of the default. */
  readonly width: number;
  /** Line alpha, as a multiple of the default. */
  readonly brightness: number;
}

export interface Look {
  readonly parts: { readonly [P in LookPart]: PartLook };
  /** How much of the wheel the stage shows: 0 the reference's arc, 1 the whole wheel. */
  readonly zoom: number;
}

/** A slider's range and step. */
export interface Range {
  readonly min: number;
  readonly max: number;
  readonly step: number;
}

export interface PartSpec {
  readonly label: string;
  /** What the part is, for the settings menu. */
  readonly description: string;
  readonly width: Range;
  readonly brightness: Range;
}

const STEP = 0.05;

export const LOOK_SPECS: { readonly [P in LookPart]: PartSpec } = {
  strands: {
    label: "Strands",
    description: "The dim lines from the nodes to the wheel",
    width: { min: 0.5, max: 3, step: STEP },
    // The default is the flash-safe ceiling (DIM_MAX): it can only be turned down.
    brightness: { min: 0.2, max: 1, step: STEP },
  },
  bullets: {
    label: "Bullets",
    description:
      "The bright heads that shoot along the strands, their nodes' rings and the bars they hit",
    width: { min: 0.5, max: 2, step: STEP },
    brightness: { min: 0.3, max: 1, step: STEP },
  },
  mesh: {
    label: "Mesh",
    description: "The dependency arcs inside the wheel",
    width: { min: 0.5, max: 2.5, step: STEP },
    brightness: { min: 0.3, max: 2, step: STEP },
  },
  nodes: {
    label: "Nodes",
    description: "The functions and tests the strands fire from",
    width: { min: 0.5, max: 2.5, step: STEP },
    brightness: { min: 0.3, max: 2, step: STEP },
  },
  lines: {
    label: "Lines outside",
    description: "The lines that bounce out of a section when its strands hit it",
    width: { min: 0.5, max: 3, step: STEP },
    // Like the strands: at most the flash-safe ceiling.
    brightness: { min: 0.2, max: 1, step: STEP },
  },
};

export const ZOOM_RANGE: Range = { min: 0, max: 1, step: 0.01 };

const DEFAULT_PART: PartLook = { width: 1, brightness: 1 };

export const DEFAULT_LOOK: Look = {
  parts: {
    strands: DEFAULT_PART,
    bullets: DEFAULT_PART,
    mesh: DEFAULT_PART,
    nodes: DEFAULT_PART,
    lines: DEFAULT_PART,
  },
  zoom: 0,
};

/** `value` within `range`, or `fallback` when it is not a finite number. */
function within(value: unknown, range: Range, fallback: number): number {
  if (typeof value !== "number" || !Number.isFinite(value)) return fallback;
  return Math.min(range.max, Math.max(range.min, value));
}

const field = (value: unknown, key: string): unknown =>
  typeof value === "object" && value !== null ? (value as Record<string, unknown>)[key] : undefined;

/**
 * A valid look from anything (a stored value, a slider): every field within its range, and
 * defaults for whatever is missing or malformed. The only way a look enters the app.
 */
export function clampLook(input: unknown): Look {
  const parts = {} as { [P in LookPart]: PartLook };
  for (const part of LOOK_PARTS) {
    const spec = LOOK_SPECS[part];
    const given = field(field(input, "parts"), part);
    parts[part] = {
      width: within(field(given, "width"), spec.width, DEFAULT_PART.width),
      brightness: within(field(given, "brightness"), spec.brightness, DEFAULT_PART.brightness),
    };
  }
  return { parts, zoom: within(field(input, "zoom"), ZOOM_RANGE, DEFAULT_LOOK.zoom) };
}

/** A copy of `look` with one part's width or brightness set (clamped). */
export function withPart(look: Look, part: LookPart, key: keyof PartLook, value: number): Look {
  return clampLook({
    ...look,
    parts: { ...look.parts, [part]: { ...look.parts[part], [key]: value } },
  });
}

/** Whether two looks draw the same. */
export function sameLook(a: Look, b: Look): boolean {
  if (a.zoom !== b.zoom) return false;
  for (const part of LOOK_PARTS) {
    if (a.parts[part].width !== b.parts[part].width) return false;
    if (a.parts[part].brightness !== b.parts[part].brightness) return false;
  }
  return true;
}

/** Where a viewer's look is kept: `localStorage`, versioned so a future shape can migrate. */
export const LOOK_KEY = "repro.look/1";

/** The parts of `Storage` the look uses (a stub in tests). */
export type LookStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;

/**
 * The stored look, or the default. Storage can be missing or throw (private windows, blocked
 * site data), and its contents can be anything: both fall back to the default.
 */
export function loadLook(storage: LookStorage | null): Look {
  if (storage === null) return DEFAULT_LOOK;
  try {
    const text = storage.getItem(LOOK_KEY);
    return text === null ? DEFAULT_LOOK : clampLook(JSON.parse(text));
  } catch {
    return DEFAULT_LOOK;
  }
}

/** Keeps `look` for this viewer (removes the entry at the default). Never throws. */
export function saveLook(storage: LookStorage | null, look: Look): void {
  if (storage === null) return;
  try {
    if (sameLook(look, DEFAULT_LOOK)) storage.removeItem(LOOK_KEY);
    else storage.setItem(LOOK_KEY, JSON.stringify(look));
  } catch {
    // Storage full or blocked: the look still applies for this visit.
  }
}
