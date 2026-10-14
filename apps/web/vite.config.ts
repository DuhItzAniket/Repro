import { randomBytes } from "node:crypto";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { defineConfig, type Plugin } from "vite";
import { configDefaults } from "vitest/config";

const require = createRequire(import.meta.url);

/**
 * Ships the font's licence next to the font files (OFL-1.1 requires the licence to accompany
 * redistributed font software). It is read from the installed package, so it always matches
 * the font version.
 */
export function fontLicence(): Plugin {
  return {
    name: "repro:font-licence",
    apply: "build",
    generateBundle() {
      const path = require.resolve("@fontsource-variable/jetbrains-mono/LICENSE");
      this.emitFile({
        type: "asset",
        fileName: "assets/JetBrainsMono-OFL.txt",
        source: readFileSync(path, "utf8"),
      });
    },
  };
}

/**
 * The size gate's self-test (B12): with REPRO_INJECT=size the build appends 400 kB of random
 * (incompressible) data to the entry chunk, which size-limit must reject. Never set otherwise.
 */
export function injectedBloat(): Plugin {
  return {
    name: "repro:inject-size",
    apply: "build",
    renderChunk(code, chunk) {
      if (process.env.REPRO_INJECT !== "size" || !chunk.isEntry) return null;
      const bloat = randomBytes(300 * 1024).toString("base64");
      return `${code}\nglobalThis.__reproInjected = "${bloat}";\n`;
    },
  };
}

export default defineConfig({
  plugins: [fontLicence(), injectedBloat()],
  test: {
    // Playwright specs (e2e/, gate/) run in their own runner.
    exclude: [...configDefaults.exclude, "e2e/**", "gate/**"],
    // SDLC.md §5: the projections and the store are at least 90% covered (`pnpm coverage`).
    coverage: {
      provider: "v8",
      include: ["src/model/**"],
      exclude: ["**/*.test.ts", "src/model/test-support.ts"],
      thresholds: { lines: 90, statements: 90, functions: 90 },
      reporter: ["text-summary"],
    },
  },
});
