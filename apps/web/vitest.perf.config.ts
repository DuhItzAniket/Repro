// The frame-cost gate (B12) runs on its own: nightly in CI, and on demand with `pnpm perf`.
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["src/perf/**/*.perf.ts"],
    // One file, run alone, so timings are not shared with other tests.
    fileParallelism: false,
  },
});
