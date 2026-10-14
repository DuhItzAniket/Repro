// B15: the viewer's look, clamped to flash-safe ranges and kept per viewer.
import { describe, expect, it } from "vitest";
import {
  clampLook,
  DEFAULT_LOOK,
  LOOK_KEY,
  LOOK_PARTS,
  LOOK_SPECS,
  type LookStorage,
  loadLook,
  sameLook,
  saveLook,
  withPart,
  ZOOM_RANGE,
} from "./look";

/** An in-memory storage, optionally one that throws like blocked site data. */
function memory(throws = false): LookStorage & { data: Map<string, string> } {
  const data = new Map<string, string>();
  const guard = () => {
    if (throws) throw new DOMException("blocked", "SecurityError");
  };
  return {
    data,
    getItem: (key) => {
      guard();
      return data.get(key) ?? null;
    },
    setItem: (key, value) => {
      guard();
      data.set(key, value);
    },
    removeItem: (key) => {
      guard();
      data.delete(key);
    },
  };
}

describe("look ranges", () => {
  it("defaults every part to its own look (×1) and the arc view", () => {
    for (const part of LOOK_PARTS) {
      expect(DEFAULT_LOOK.parts[part]).toEqual({ width: 1, brightness: 1 });
      const spec = LOOK_SPECS[part];
      for (const range of [spec.width, spec.brightness]) {
        expect(range.min).toBeLessThanOrEqual(1);
        expect(range.max).toBeGreaterThanOrEqual(1);
      }
    }
    expect(DEFAULT_LOOK.zoom).toBe(ZOOM_RANGE.min);
  });

  it("never lets the uncounted dim lines brighten past their flash-safe ceiling", () => {
    // Strands and lines outside the wheel are MAX-blended at DIM_MAX and not counted by the
    // flash governor: brightness ×1 is their ceiling.
    expect(LOOK_SPECS.strands.brightness.max).toBe(1);
    expect(LOOK_SPECS.lines.brightness.max).toBe(1);
    const bright = clampLook({ parts: { strands: { brightness: 5 }, lines: { brightness: 2 } } });
    expect(bright.parts.strands.brightness).toBe(1);
    expect(bright.parts.lines.brightness).toBe(1);
  });

  it("clamps anything to a valid look, with defaults for what is missing or malformed", () => {
    expect(clampLook(undefined)).toEqual(DEFAULT_LOOK);
    expect(clampLook("nonsense")).toEqual(DEFAULT_LOOK);
    expect(clampLook({ parts: null, zoom: "far" })).toEqual(DEFAULT_LOOK);
    const look = clampLook({
      parts: { mesh: { width: 100, brightness: -1 }, nodes: { width: Number.NaN } },
      zoom: 7,
    });
    expect(look.parts.mesh).toEqual({
      width: LOOK_SPECS.mesh.width.max,
      brightness: LOOK_SPECS.mesh.brightness.min,
    });
    expect(look.parts.nodes.width).toBe(1);
    expect(look.zoom).toBe(ZOOM_RANGE.max);
  });

  it("sets one part's width or brightness and leaves the rest", () => {
    const look = withPart(DEFAULT_LOOK, "bullets", "width", 1.5);
    expect(look.parts.bullets).toEqual({ width: 1.5, brightness: 1 });
    expect(look.parts.strands).toEqual(DEFAULT_LOOK.parts.strands);
    expect(sameLook(look, DEFAULT_LOOK)).toBe(false);
    expect(sameLook(withPart(look, "bullets", "width", 1), DEFAULT_LOOK)).toBe(true);
    expect(withPart(DEFAULT_LOOK, "nodes", "brightness", 99).parts.nodes.brightness).toBe(
      LOOK_SPECS.nodes.brightness.max,
    );
  });
});

describe("look storage", () => {
  it("keeps a viewer's look across loads, and nothing at the default", () => {
    const storage = memory();
    const look = clampLook({ parts: { mesh: { brightness: 0.5 } }, zoom: 1 });
    saveLook(storage, look);
    expect(storage.data.has(LOOK_KEY)).toBe(true);
    expect(loadLook(storage)).toEqual(look);
    saveLook(storage, DEFAULT_LOOK);
    expect(storage.data.has(LOOK_KEY)).toBe(false);
    expect(loadLook(storage)).toEqual(DEFAULT_LOOK);
  });

  it("clamps what it reads, so a tampered entry cannot break the flash ceiling", () => {
    const storage = memory();
    storage.data.set(LOOK_KEY, JSON.stringify({ parts: { strands: { brightness: 3 } } }));
    expect(loadLook(storage).parts.strands.brightness).toBe(1);
    storage.data.set(LOOK_KEY, "{not json");
    expect(loadLook(storage)).toEqual(DEFAULT_LOOK);
  });

  it("falls back to the default when storage is missing or throws, and never throws itself", () => {
    expect(loadLook(null)).toEqual(DEFAULT_LOOK);
    const blocked = memory(true);
    expect(loadLook(blocked)).toEqual(DEFAULT_LOOK);
    expect(() => saveLook(blocked, clampLook({ zoom: 1 }))).not.toThrow();
    expect(() => saveLook(null, DEFAULT_LOOK)).not.toThrow();
  });
});
