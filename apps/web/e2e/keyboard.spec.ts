import { expect, test, type Locator, type Page } from "@playwright/test";
import { loadWorld, onlyOnProjects, signInAs } from "./support/world";

/**
 * Keyboard-only journey (frontend_verification §16): Today → Inbox → Approvals → the review
 * page → the quote under review, with Tab and Enter only, and a visible focus indicator on
 * every stop. Desktop project only (phones have no hardware keyboard by default).
 */

/** Presses Tab until `target` has focus (at most `max` presses), asserting focus is visible. */
async function tabTo(page: Page, target: Locator, max = 60): Promise<void> {
  for (let i = 0; i < max; i += 1) {
    await page.keyboard.press("Tab");
    if (await target.evaluate((element) => element === document.activeElement).catch(() => false)) {
      const visible = await target.evaluate((element) => {
        const style = getComputedStyle(element);
        return element.matches(":focus-visible") && (style.outlineStyle !== "none" || style.boxShadow !== "none");
      });
      expect(visible, "focus indicator visible").toBe(true);
      return;
    }
  }
  throw new Error(`Tab never reached ${target.toString()}`);
}

test("Today → Inbox → review → quote with the keyboard only", async ({ page, request }) => {
  onlyOnProjects("desktop");
  await loadWorld(request);
  await signInAs(page, "SAHIL");
  await page.goto("/today");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();

  // The skip link is the first stop and moves focus to the main region.
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to main content" })).toBeFocused();

  await tabTo(page, page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: /^Inbox/ }));
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/inbox$/);
  await expect(page.getByRole("heading", { level: 1 })).toBeFocused();

  await tabTo(page, page.getByRole("link", { name: /^Approvals/ }).first());
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/inbox\/approvals$/);

  const firstRequest = page.getByRole("main").getByRole("link", { name: /LK-QT-/ }).first();
  await tabTo(page, firstRequest);
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/inbox\/approvals\/[0-9a-f-]{36}$/);
  await expect(page.getByRole("button", { name: "Approve" })).toBeVisible();

  await tabTo(page, page.getByRole("main").getByRole("link", { name: /^Open LK-QT-/ }).first());
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/sales\/quotes\/[0-9a-f-]{36}$/);
  await expect(page.getByRole("heading", { level: 1 })).toContainText("LK-QT-");
});
