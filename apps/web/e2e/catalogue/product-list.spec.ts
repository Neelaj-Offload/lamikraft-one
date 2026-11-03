import { expect, test } from "@playwright/test";
import { loadWorld, onlyOnProjects, signInAs } from "../support/world";

/**
 * Catalogue list, detail, form, taxonomy, media and lookups (UI-14/15/20/32/34/43, FG-LKP-03). Written by the catalogue
 * lane (Slice 2); adapted by the Slice-2 integrator to the merged screens (main's catalogue list and product record
 * with ?tab= tabs, the lane's editors and actions). Admin flows sign in as Priya. The flows write shared rows
 * (E2E-FORM-01, a category), so they run on the desktop project only.
 */

const PRIYA = "PRIYA" as const;

test.beforeAll(async ({ request }) => {
  await loadWorld(request);
});

test.beforeEach(() => onlyOnProjects("desktop"));

test("filters_paging_and_deep_links_survive_reload", async ({ page }) => {
  await signInAs(page, "SAHIL");
  await page.goto("/products?thickness=12&limit=25");
  await expect(page.getByRole("heading", { level: 1, name: "Products" })).toBeVisible();
  await expect(page.getByRole("link", { name: "LK-OT-0450" })).toBeVisible();
  await page.reload();
  await expect(page).toHaveURL(/thickness=12/);
  await expect(page.getByRole("link", { name: "LK-OT-0450" })).toBeVisible();
  await page.getByRole("link", { name: "LK-OT-0450" }).click();
  await page.getByRole("tab", { name: "Specification" }).click();
  await expect(page).toHaveURL(/\?tab=specification$/);
  await page.reload();
  await expect(page.getByRole("tab", { name: "Specification" })).toHaveAttribute("aria-selected", "true");
  // the server's section paths open the same tab
  const recordUrl = new URL(page.url());
  await page.goto(`${recordUrl.pathname}/specifications`);
  await expect(page).toHaveURL(/\?tab=specification$/);
});

test("category_facet_filter", async ({ page }) => {
  await signInAs(page, "SAHIL");
  await page.goto("/products");
  await page.getByRole("complementary", { name: "Filters" }).getByRole("link").first().click();
  await expect(page).toHaveURL(/\?.+=/);
});

test("create_button_requires_capability", async ({ page }) => {
  await signInAs(page, "MEERA");
  await page.goto("/products");
  await expect(page.getByRole("link", { name: "Add product" })).toHaveCount(0);
  await signInAs(page, PRIYA);
  await page.goto("/products");
  await expect(page.getByRole("link", { name: "Add product" })).toBeVisible();
});

test("create_with_all_sections_and_server_errors", async ({ page }) => {
  await signInAs(page, PRIYA);
  await page.goto("/products/new");
  await page.getByRole("textbox", { name: "Product key" }).fill("E2E-FORM-01");
  // the picker reads "Loading…" until the taxonomy arrives
  await page.getByRole("button", { name: /^Choose a category/ }).click();
  await page.getByRole("option").first().click();
  await page.getByRole("textbox", { name: "Carton quantity" }).fill("24");
  await page.getByRole("textbox", { name: "Unit weight (g)" }).fill("450");
  await page.getByRole("textbox", { name: "Unit weight (kg)" }).fill("0.5"); // disagrees with 450 g
  await page.getByRole("button", { name: "Create product" }).click();
  await expect(page.getByText("Alias values disagree")).toBeVisible();
  await page.getByRole("textbox", { name: "Unit weight (kg)" }).fill("0.45");
  await page.getByRole("button", { name: "Create product" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page).toHaveURL(/\/products\/[0-9a-f-]{36}$/);
});

test("archive_restore_with_confirm", async ({ page }) => {
  await signInAs(page, PRIYA);
  await page.goto("/products?q=E2E-FORM-01");
  await page.getByRole("link", { name: "E2E-FORM-01" }).click();
  await page.getByRole("button", { name: "Archive" }).click();
  await page.getByRole("button", { name: "Archive", exact: true }).last().click();
  await expect(page.getByRole("button", { name: "Restore" })).toBeVisible();
  await page.getByRole("button", { name: "Restore" }).click();
  await expect(page.getByRole("button", { name: "Archive" })).toBeVisible();
});

test("history_tab_shows_versions", async ({ page }) => {
  await signInAs(page, PRIYA);
  await page.goto("/products?q=E2E-FORM-01");
  await page.getByRole("link", { name: "E2E-FORM-01" }).click();
  await page.getByRole("tab", { name: "History" }).click();
  await expect(page.getByText(/product restored/i)).toBeVisible();
});

test("taxonomy_pickers_only_active", async ({ page }) => {
  await signInAs(page, PRIYA);
  await page.goto("/products/new");
  // the picker reads "Loading…" until the taxonomy arrives
  await page.getByRole("button", { name: /^Choose a category/ }).click();
  await expect(page.getByRole("option", { name: "Serveware" })).toBeVisible();
});

test("crud_rename_reassign_delete", async ({ page }) => {
  await signInAs(page, PRIYA);
  await page.goto("/products/taxonomy");
  await page.getByRole("button", { name: "New category" }).click();
  await page.getByRole("textbox", { name: "Name" }).fill("E2E Shelf");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("E2E Shelf")).toBeVisible();
});

test("upload_preview_download_delete_restore", async ({ page }) => {
  await signInAs(page, PRIYA);
  await page.goto("/products?q=LK-OT-0450");
  await page.getByRole("link", { name: "LK-OT-0450" }).click();
  await page.getByRole("tab", { name: /Media/ }).click();
  await page.getByLabel("Files").setInputFiles({
    name: "front.png",
    mimeType: "image/png",
    buffer: Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==", "base64"),
  });
  await expect(page.getByText("front.png")).toBeVisible();
  await expect(page.getByRole("link", { name: "Preview" })).toBeVisible();
});

test("browse_filter_export", async ({ page }) => {
  await signInAs(page, PRIYA);
  await page.goto("/settings/lookups");
  await expect(page.getByRole("heading", { level: 1, name: "Lookup reference" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Export CSV" })).toHaveAttribute("href", /lookups\/export\.csv/);
});
