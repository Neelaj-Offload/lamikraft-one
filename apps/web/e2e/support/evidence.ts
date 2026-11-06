import { mkdirSync } from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";

/**
 * Checkpoint-6 evidence (docs/evidence/checkpoint-6/): screenshots at 1440 and 390 px, light and dark, taken only when
 * `LK_E2E_EVIDENCE=cp6`. `e2e/evidence-cp6.spec.ts` uses it for the screens any session can reach; the scenario specs
 * use it for records they create (an invoice, a sample) and for screens behind an MFA step-up (migration, backups),
 * keeping their own session.
 */

export const CP6 = process.env.LK_E2E_EVIDENCE === "cp6";
export const CP6_OUT = path.resolve(__dirname, "../../../../docs/evidence/checkpoint-6");
const WIDTHS = [
  { name: "1440", width: 1440, height: 900 },
  { name: "390", width: 390, height: 844 },
] as const;
const THEMES = ["light", "dark"] as const;

/** Four screenshots of `url` in the page's current session; a no-op unless `LK_E2E_EVIDENCE=cp6`. */
export async function shoot(page: Page, name: string, url: string): Promise<void> {
  if (!CP6) return;
  test.setTimeout(test.info().timeout + 90_000);
  mkdirSync(CP6_OUT, { recursive: true });
  const baseURL = test.info().project.use.baseURL!;
  for (const theme of THEMES) {
    for (const width of WIDTHS) {
      await page.context().addCookies([{ name: "lk_ui", value: `theme=${theme}&motion=reduced`, url: baseURL }]);
      await page.setViewportSize({ width: width.width, height: width.height });
      await page.goto(url);
      await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
      await expect(page.getByRole("main")).toBeVisible();
      await page.waitForLoadState("networkidle");
      await page.waitForTimeout(800);
      await page.screenshot({ path: path.join(CP6_OUT, `${name}-${width.name}-${theme}.png`), fullPage: false });
    }
  }
  await page.setViewportSize({ width: 1440, height: 900 });
}
