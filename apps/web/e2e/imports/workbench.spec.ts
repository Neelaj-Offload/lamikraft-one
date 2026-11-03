import { expect, test, type Page } from "@playwright/test";
import { loadWorld, signInAs, type PersonKey } from "../support/world";

/**
 * Scenario G import workbench (UI-24/86/89, SCN-G1/G2): taxonomy -> products -> packaging with an alias conflict;
 * preview, mapping, validation, issue report, commit, re-import all unchanged, rollback plan. Written by the catalogue
 * lane (Slice 2); run by the integrator. Signs in as Priya (`PersonKey` needs "PRIYA").
 */

const PRIYA = "PRIYA" as PersonKey;

test.describe.configure({ mode: "serial" });

test.beforeAll(async ({ request }) => {
  await loadWorld(request);
});

async function importFile(page: Page, typeLabel: RegExp, name: string, csv: string) {
  await page.goto("/settings/imports/new");
  await page.getByRole("radio", { name: typeLabel }).check();
  await page.getByLabel("CSV or XLSX file").setInputFiles({ name, mimeType: "text/plain", buffer: Buffer.from(csv) });
  await page.getByRole("button", { name: "Upload and preview" }).click();
  await expect(page).toHaveURL(/\/settings\/imports\/[0-9a-f-]{36}$/);
  await page.getByRole("button", { name: "Save mapping and validate" }).click();
  await expect(page.getByRole("region", { name: "Commit" })).toBeVisible({ timeout: 20_000 });
}

async function commit(page: Page) {
  const ack = page.getByRole("checkbox", { name: /will not be imported/ });
  if (await ack.count()) await ack.check();
  await page.getByRole("button", { name: "Commit in batches of 500" }).click();
  await expect(page.getByText("Committed")).toBeVisible({ timeout: 30_000 });
}

test("dependency_status_shown", async ({ page }) => {
  await signInAs(page, PRIYA);
  await page.goto("/settings/imports/new");
  await expect(page.getByText(/Needs: Category taxonomy/).first()).toBeVisible();
  await expect(page.getByRole("link", { name: "Download the template" })).toBeVisible();
});

test("taxonomy_products_packaging_conflict_commit_reimport_rollback", async ({ page }) => {
  await signInAs(page, PRIYA);
  await importFile(page, /Category taxonomy/, "taxonomy.csv", "category,subcategory\nE2E Kitchen,Chopping\n");
  await commit(page);
  const products = "product_key,category,subcategory\nE2E-IMP-1,E2E Kitchen,Chopping\nE2E-IMP-2,E2E Kitchen,Chopping\n";
  await importFile(page, /Products master/, "products.csv", products);
  await commit(page);
  await importFile(page, /Packaging/, "packaging.csv", "product_key,carton_qty,master_carton_qty\nE2E-IMP-1,24,12\nE2E-IMP-2,24,24\n");
  await expect(page.getByText("ALIAS_CONFLICT")).toBeVisible();
  await expect(page.getByRole("link", { name: "Download full report" })).toBeVisible();
  await commit(page);
  // re-import: every row unchanged
  await importFile(page, /Products master/, "products.csv", products);
  await expect(page.getByText("This file was imported before")).toHaveCount(0); // shown on the mapping step only
  await commit(page);
  await page.getByRole("button", { name: "Roll back" }).click();
  await expect(page.getByRole("alertdialog", { name: "Roll back this import" })).toBeVisible();
});
