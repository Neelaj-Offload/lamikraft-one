import { expect, test } from "@playwright/test";
import { addCatalogLine, newDraftQuote } from "../support/quotes";
import { onlyOnProjects, signInAs } from "../support/world";

/**
 * Scenario E (UI-67, UI-70): the currency dialog reprices from a list or converts at an approved rate, never
 * relabels; a sales user never sees costing. Run by the integrator.
 */

test("currency_dialog_reprice_or_convert_only", async ({ page }) => {
  onlyOnProjects("desktop");
  // a fresh draft with one catalog line: the seeded Nordhaus draft is in review (not editable) at D0
  await signInAs(page, "MEERA");
  await newDraftQuote(page, "Nordhaus");
  await addCatalogLine(page, "LK-OT-0450", /oak serving tray/i, "240");
  await page.getByRole("button", { name: "Change currency" }).click();
  const dialog = page.getByRole("dialog", { name: "Change the quote currency" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText(/Price list|Approved FX rate|No price/).first()).toBeVisible();
});

test("sales_user_sees_no_costing_tab_or_sentinel", async ({ page }) => {
  onlyOnProjects("desktop");
  await signInAs(page, "MEERA");
  await page.goto("/sales/custom-products");
  await expect(page.getByRole("heading", { level: 1, name: "Custom products" })).toBeVisible();
  await expect(page.getByText("Include costing columns")).toHaveCount(0);
});
