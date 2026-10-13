// Builds the app for production and checks what ships: the font with its licence, the
// fixtures, and JS within the 300 kB gzip budget (DESIGN.md; size-limit takes over in B12).
import { mkdtempSync, readdirSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";
import { build } from "vite";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

const APP = fileURLToPath(new URL("..", import.meta.url));
const JS_BUDGET_GZIP = 300 * 1024;
let out: string;
let assets: string[];

beforeAll(async () => {
  out = mkdtempSync(join(tmpdir(), "repro-web-build-"));
  await build({ root: APP, logLevel: "silent", build: { outDir: out, emptyOutDir: true } });
  assets = readdirSync(join(out, "assets"));
}, 120_000);

afterAll(() => {
  rmSync(out, { recursive: true, force: true });
});

describe("production build", () => {
  it("ships the font's OFL licence next to the font files", () => {
    expect(assets.some((f) => /^jetbrains-mono-latin-wght-normal-.*\.woff2$/.test(f))).toBe(true);
    expect(assets).toContain("JetBrainsMono-OFL.txt");
    const licence = readFileSync(join(out, "assets", "JetBrainsMono-OFL.txt"), "utf8");
    expect(licence).toContain("SIL Open Font License, Version 1.1");
    expect(licence).toContain("JetBrains Mono Project Authors");
  });

  it("ships the fixtures the app replays", () => {
    expect(assets.some((f) => f.startsWith("demo-run-") && f.endsWith(".jsonl"))).toBe(true);
    expect(assets.some((f) => f.startsWith("stress-run-") && f.endsWith(".jsonl"))).toBe(true);
  });

  it("keeps JavaScript within the 300 kB gzip budget", () => {
    const js = assets.filter((f) => f.endsWith(".js"));
    const gzip = js.reduce(
      (sum, f) => sum + gzipSync(readFileSync(join(out, "assets", f))).length,
      0,
    );
    expect(js.length).toBeGreaterThan(0);
    expect(gzip).toBeLessThan(JS_BUDGET_GZIP);
  });
});
