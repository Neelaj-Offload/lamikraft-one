/**
 * Quote helpers for the commercial specs: a fresh draft per test (the seeded quotes are in fixed states that other
 * specs read), choosing an option in a server-searched React Aria combobox, and adding a catalog line.
 */

import { expect, type Locator, type Page } from "@playwright/test";

/** Types into a server-searched combobox and chooses the first option matching `option` (opens the list if needed). */
export async function chooseFromCombobox(page: Page, combobox: Locator, text: string, option: RegExp): Promise<void> {
  await combobox.fill(text);
  const match = page.getByRole("option", { name: option }).first();
  await expect(async () => {
    if (!(await match.isVisible())) await combobox.press("ArrowDown");
    await expect(match).toBeVisible({ timeout: 1_500 });
  }).toPass({ timeout: 15_000 });
  await match.click();
}

/** Creates a draft for the customer through the New quote page and returns the workspace path. */
export async function newDraftQuote(page: Page, customer = "Nordhaus"): Promise<string> {
  await page.goto("/sales/quotes/new");
  await chooseFromCombobox(page, page.getByRole("combobox", { name: "Customer" }), customer, new RegExp(customer));
  await page.getByRole("button", { name: "Create draft" }).click();
  await expect(page).toHaveURL(/\/sales\/quotes\/[0-9a-f-]{36}$/);
  return new URL(page.url()).pathname;
}

/** Adds a catalog line through the workspace's product picker. */
export async function addCatalogLine(page: Page, productText: string, quantity: string): Promise<void> {
  const section = page.getByRole("region", { name: "Add a product" });
  await chooseFromCombobox(page, section.getByRole("combobox", { name: "Product" }), productText, /./);
  await section.getByRole("textbox", { name: /^Quantity/ }).fill(quantity);
  await section.getByRole("button", { name: "Add line" }).click();
  await expect(page.getByText("Line added").first()).toBeVisible();
}
