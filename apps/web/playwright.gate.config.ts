/**
 * Gate C (C08): the cockpit against the real engine on a real repository. The spec starts
 * `repro run` and `repro replay` itself, so there is no web server here. It needs a built
 * cockpit (`pnpm build`), the Python environment (`uv sync`) and a clone of the target named by
 * REPRO_GATE_REPO (see gate/gate-c.spec.ts); CI's `gate-c` job provides all three.
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
