import { expect, test } from "@playwright/test";
import { onlyOnProjects, signInAs } from "../support/world";

/**
 * Custom products (UI-17, UI-69, UI-71): Meera creates a custom product with legacy fields, edits it, duplicates it
 * ("X (Copy)") and sees the CSV export link; the costing section stays restricted for her. Run by the integrator.
 */

test("create_edit_duplicate_export", async ({ page }) => {
  onlyOnProjects("desktop");
  const name = `E2E tray ${Date.now().toString(36)}`;
  await signInAs(page, "MEERA");
  await page.goto("/sales/custom-products/new");
  await page.getByRole("textbox", { name: "Product name" }).fill(name);
  await page.getByRole("textbox", { name: "Dimensions" }).fill("520 x 330 mm");
  await page.getByRole("textbox", { name: "Decor no." }).fill("0120");
  await page.getByRole("button", { name: "Create custom product" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText(name);
  await expect(page.getByText("Costing is restricted")).toBeVisible();

  await page.getByRole("textbox", { name: "Finish" }).fill("Matt lacquer");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("Saved")).toBeVisible();

  await page.getByRole("button", { name: "Duplicate" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText(`${name} (Copy)`);

  await page.goto("/sales/custom-products");
  const exportLink = page.getByRole("link", { name: "Export CSV" });
  await expect(exportLink).toHaveAttribute("href", /\/api\/v1\/sales\/custom-products\/export\.csv/);
});
