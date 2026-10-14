// Visual regression (B12): the cockpit at frozen moments of the demo run. REPRO_INJECT=visual
// injects a visible change, which CI checks these tests catch.
import { expect, type Page, test } from "@playwright/test";
import type { RenderOptions, TestHook } from "../src/test-hook";

const END = 48_716;
const MOMENTS = [12_000, 24_500, 30_500, END];

async function renderAt(page: Page, t: number, options: RenderOptions = {}) {
  await page.goto("/?test");
  const { litPixels } = await page.evaluate(
    ([at, opts]) => (window as unknown as { __reproTest: TestHook }).__reproTest.renderAt(at, opts),
    [t, options] as const,
  );
  // A blank stage would make a meaningless baseline: WebGL must really be drawing.
  expect(litPixels).toBeGreaterThan(10_000);
  if (process.env.REPRO_INJECT === "visual") {
    // A plausible regression: every panel shifted by one pixel.
    await page.addStyleTag({ content: ".panel { transform: translateX(1px); }" });
  }
}

test.describe("cockpit", () => {
  for (const t of MOMENTS) {
    test(`at ${t} ms`, async ({ page }) => {
      await renderAt(page, t);
      await expect(page).toHaveScreenshot(`cockpit-${t}.png`);
    });
  }

  test("with a claim focused and the evidence drawer open", async ({ page }) => {
    await renderAt(page, END, { focus: { kind: "claim", id: "C3" } });
    await expect(page).toHaveScreenshot("cockpit-focus-C3.png");
  });

  test("with reduced motion during the trace burst", async ({ page }) => {
    await renderAt(page, 24_500, { reduced: true });
    await expect(page).toHaveScreenshot("cockpit-reduced-24500.png");
  });

  test("showing the whole wheel during the trace burst (B15)", async ({ page }) => {
    await renderAt(page, 24_500, { look: { zoom: 1 } });
    await expect(page).toHaveScreenshot("cockpit-whole-24500.png");
  });

  test("with the stage settings open and a restyled look (B15)", async ({ page }) => {
    const look = { parts: { mesh: { brightness: 0.6 }, strands: { width: 2 } } };
    await renderAt(page, 24_500, { look, settings: true });
    await expect(page).toHaveScreenshot("cockpit-settings-24500.png");
  });
});
