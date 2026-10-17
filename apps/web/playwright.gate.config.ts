/**
 * The gates' browser tests: the cockpit against the real engine. The specs start `repro run`
 * and `repro replay` themselves, so there is no web server here. Both need a built cockpit
 * (`pnpm build`) and the Python environment (`uv sync`). Gate C (C08) also needs a clone of
 * its target named by REPRO_GATE_REPO (see gate/gate-c.spec.ts); Gate D builds Repro's own
 * fixture repositories and needs the package index (and Docker for containers). CI's `gate-c`
 * and `gate-d` jobs run one spec each. `demo.spec.ts` is not a gate: it records the guide's
 * demo (docs/guide/demo.md), and only when REPRO_DEMO_OUT is set.
 */
import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "gate",
  fullyParallel: false,
  workers: 1,
  timeout: 180_000,
  retries: 0,
  forbidOnly: Boolean(process.env.CI),
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report-gate" }]],
  outputDir: "test-results-gate",
  use: {
    ...devices["Desktop Chrome"],
    // An installed browser instead of Playwright's Chromium, e.g. "msedge" on Windows.
    ...(process.env.REPRO_GATE_CHANNEL ? { channel: process.env.REPRO_GATE_CHANNEL } : {}),
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 1,
    trace: "retain-on-failure",
    launchOptions: {
      args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"],
    },
  },
});
