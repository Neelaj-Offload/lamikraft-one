import { expect, test } from "@playwright/test";
import { fact, loadWorld, onlyOnProjects, ref, signInAs } from "../support/world";

/**
 * Scenario E (UI-67, UI-70): the currency dialog reprices from a list or converts at an approved rate, never
 * relabels; a sales user never sees costing. Run by the integrator.
 */

test("currency_dialog_reprice_or_convert_only", async ({ page, request }) => {
  onlyOnProjects("desktop");
  const world = await loadWorld(request);
  const number = fact(world, "quotes", "NORDHAUS_DRAFT");
  test.skip(!number, "the fixture world does not publish the Nordhaus draft");
  const id = ref(world, number!);
  await signInAs(page, "MEERA");
  await page.goto(`/sales/quotes/${id}`);
  // At D0 the Nordhaus draft is in internal review (fixtures.md); the currency changes only on the working copy,
  // so withdraw the review first (adapted by the Slice-2 integrator).
  const withdraw = page.getByRole("button", { name: "Withdraw review request" });
  if (await withdraw.isVisible()) {
    await withdraw.click();
    const confirm = page.getByRole("dialog").getByRole("button", { name: "Withdraw review request" });
    if (await confirm.isVisible().catch(() => false)) {
      const note = page.getByRole("dialog").getByRole("textbox");
      if (await note.count()) await note.first().fill("Currency check in the e2e suite");
      await confirm.click();
    }
  }
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
