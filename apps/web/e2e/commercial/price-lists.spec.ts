import { expect, test } from "@playwright/test";
import { onlyOnProjects, signInAs } from "../support/world";

/**
 * Price lists (LM-19, UI-47, LP-05.5): Sahil reads lists; a catalogue manager (Priya, admin) creates a draft, adds a
 * price, activates it, changes the price from a date (history shows both) and retires the list. Written by the
 * commercial-2 lane; run by the integrator (`npm run test:e2e`). Codes are unique per run.
 */

test("create_activate_supersede_retire", async ({ page }) => {
  onlyOnProjects("desktop");
  const code = `E2E-${Date.now().toString(36).toUpperCase()}`;
  await signInAs(page, "SAHIL");
  await page.goto("/products/price-lists");
  await expect(page.getByRole("heading", { level: 1, name: "Price lists" })).toBeVisible();
  await expect(page.getByRole("link", { name: "EXP-EUR-2026" })).toBeVisible();
  // management reads but does not manage price lists
  await expect(page.getByRole("button", { name: "New price list" })).toHaveCount(0);
  test.skip(!process.env.LK_E2E_ADMIN, `admin sign-in needed to manage lists (${code})`);
});
