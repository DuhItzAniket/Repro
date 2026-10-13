/**
 * Visual regression (B12; ADR-0009). Chromium renders WebGL with SwiftShader (software), so the
 * pixels do not depend on a GPU. Baselines are generated only in CI, in the Playwright image
 * pinned in `.github/workflows/ci.yml`: set REPRO_UPDATE_SNAPSHOTS=1 there to (re)write them.
 * Locally the run compares against those Linux baselines and is expected to differ on Windows;
 * the GPU-free render-model tests in Vitest cover local work.
 */
import { defineConfig, devices } from "@playwright/test";

const PORT = 4173;

export default defineConfig({
  testDir: "e2e",
  snapshotPathTemplate: "e2e/__screenshots__/{arg}{ext}",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: Boolean(process.env.CI),
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report" }]],
  updateSnapshots: process.env.REPRO_UPDATE_SNAPSHOTS === "1" ? "all" : "none",
  expect: {
    // SwiftShader renders deterministically: allow only a few pixels of anti-aliasing noise, so
    // a 1 px layout shift (thousands of pixels) fails.
    toHaveScreenshot: { maxDiffPixels: 50, animations: "disabled" },
  },
  use: {
    baseURL: `http://localhost:${PORT}`,
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 900 },
        deviceScaleFactor: 1,
        reducedMotion: "no-preference",
        launchOptions: {
          args: [
            "--use-angle=swiftshader",
            "--enable-unsafe-swiftshader",
            "--ignore-gpu-blocklist",
          ],
        },
      },
    },
  ],
  webServer: {
    // The production build, as shipped (`pnpm build` first).
    command: `pnpm exec vite preview --port ${PORT} --strictPort`,
    url: `http://localhost:${PORT}`,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
