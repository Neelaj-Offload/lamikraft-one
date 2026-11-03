import { expect, test } from "@playwright/test";
import { newDraftQuote } from "../support/quotes";
import { onlyOnProjects, signInAs } from "../support/world";

/**
 * The quote configurator (LM-43, UI-60, LP-06.1): Meera opens the configurator from a new Nordhaus draft with the
 * keyboard, types the oak tray's key and takes the exact match with Enter; the pick form shows the packaging summary
 * and the customer's default price, warns in amber when the quantity is below the order-value recommendation and
 * when the price differs from the default (then asks for a reason); back in the list, a category filter narrows the
 * options and the paging shows the range. Adding the line closes the drawer and the line appears on the quote.
 * Written by the commercial configurator follow-up lane.
 */

test("configurator_keyboard_filters_paging_and_advisories", async ({ page }) => {
  onlyOnProjects("desktop");
  await signInAs(page, "MEERA");
  await newDraftQuote(page, "Nordhaus");

  // keyboard: focus the trigger, open with Enter; the search field takes focus
  const browse = page.getByRole("button", { name: "Browse the catalogue" });
  await browse.focus();
  await page.keyboard.press("Enter");
  const drawer = page.getByRole("dialog", { name: "Find a product" });
  await expect(drawer).toBeVisible();
  const search = drawer.getByRole("searchbox", { name: "Search" });
  await expect(search).toBeFocused();
  await expect(drawer.getByText(/\d+–\d+ of \d+/)).toBeVisible();

  await page.keyboard.type("LK-OT-0450");
  await expect(drawer.getByText("Exact match")).toBeVisible();
  await expect(drawer.getByText("1–1 of 1")).toBeVisible();
  await page.keyboard.press("Enter");

  // the pick form: packaging summary, default price, amber advisories
  await expect(drawer.getByRole("heading", { name: /oak/i })).toBeVisible();
  await expect(drawer.getByText("450g · 24/ctn · Poly bag").first()).toBeVisible();
  // the engine's order-value recommendation, never presented as the product MOQ
  await expect(drawer.getByText(/^Order-value recommendation/).first()).toBeVisible();
  await expect(drawer.getByText(/Recommended MOQ|^MOQ/)).toHaveCount(0);
  const quantity = drawer.getByRole("textbox", { name: /^Quantity/ });
  await quantity.fill("100");
  await quantity.press("Tab");
  await expect(drawer.getByText(/below the order-value recommendation/)).toBeVisible();
  const price = drawer.getByRole("textbox", { name: "Unit price" });
  if (await price.isEditable()) {
    await price.fill("22");
    await price.press("Tab");
    await expect(drawer.getByText(/price differs from the default/)).toBeVisible();
    await expect(drawer.getByRole("textbox", { name: /Why does the price differ/ })).toBeVisible();
    await price.fill("24");
    await price.press("Tab");
  }

  // back to the list: filters narrow the options, paging shows the range
  await drawer.getByRole("button", { name: "Choose another product" }).click();
  await drawer.getByRole("button", { name: "Clear filters" }).click();
  await expect(search).toHaveValue("");
  await drawer.getByRole("button", { name: /Category$/ }).click();
  await page.getByRole("option", { name: /Serveware/ }).click();
  await expect(drawer.getByRole("button", { name: /Category$/ })).toContainText("Serveware");
  await expect(drawer.getByText(/\d+–\d+ of \d+/)).toBeVisible();
  await expect(drawer.getByRole("button", { name: "Previous page" })).toBeDisabled();

  // add the line
  await drawer.getByRole("button", { name: /^Choose .*oak/i }).first().click();
  const lineQuantity = drawer.getByRole("textbox", { name: /^Quantity/ });
  await lineQuantity.fill("240");
  await lineQuantity.press("Tab");
  await drawer.getByRole("button", { name: "Add to quote" }).click();
  await expect(drawer).toBeHidden();
  await expect(page.getByText("Line added").first()).toBeVisible();
  await expect(page.getByText("LK-OT-0450").first()).toBeVisible();
});
