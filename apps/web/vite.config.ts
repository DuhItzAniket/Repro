import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { defineConfig, type Plugin } from "vite";

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

export default defineConfig({
  plugins: [fontLicence()],
});
