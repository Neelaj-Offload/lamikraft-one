import { expect, test, type Page } from "@playwright/test";
import { onlyOnProjects, signInAs } from "./support/world";

/**
 * Delivery challans (PLAN Slice 2, scenario L subset; PARITY_MATRIX UI-19, UI-77, UI-80, UI-83, UI-84, LM-92):
 * Ravi (operations) creates a draft from the list, adds a catalogue line, edits its quantity (600 ms debounced save,
 * a failed save shown inline with Retry), issues it, opens the print view, downloads the PDF and the CSV and
 * duplicates it; Priya (admin) deletes a draft. Works on the Slice-1 seed: every challan here is created by the
 * test, nothing is read from the challan fixtures. Desktop and phone.
 */

test.describe.configure({ mode: "serial" });

let challanPath = "";
let challanNumber = "";

test.beforeAll(() => {
  onlyOnProjects("desktop", "phone");
});

async function pickOption(page: Page, label: RegExp, text: string) {
  const box = page.getByRole("combobox", { name: label });
  await box.fill(text);
  const option = page.getByRole("option").first();
  await expect(option).toBeVisible({ timeout: 10_000 });
  await option.click();
}

test("challan_create_duplicate_print_csv: Ravi drafts, edits, issues, prints and exports a challan", async ({ page }) => {
  await signInAs(page, "RAVI");
  await page.goto("/operations/challans");
  await expect(page.getByRole("heading", { level: 1, name: "Delivery challans" })).toBeVisible();
  await expect(page.getByLabel("Challan summary")).toBeVisible();

  await page.getByRole("link", { name: "New challan" }).click();
  await expect(page).toHaveURL(/\/operations\/challans\/new$/);
  await pickOption(page, /^Party/, "Nord");
  await page.getByRole("textbox", { name: "Reference number" }).fill("E2E-PO-1");
  await page.getByRole("button", { name: "Create draft" }).click();
  await expect(page).toHaveURL(/\/operations\/challans\/[0-9a-f-]{36}$/);
  challanPath = new URL(page.url()).pathname;
  challanNumber = ((await page.locator("header p.font-mono").first().textContent()) ?? "").trim();
  expect(challanNumber).toMatch(/^DC-\d{4}-\d{4,}$/);
  await expect(page.getByText("Add at least one line before issuing.")).toBeVisible();

  // a catalogue line: code, name, HSN/SAC and unit come from the product
  await pickOption(page, /^Product/, "oak");
  await page.getByRole("textbox", { name: "Quantity", exact: true }).fill("40");
  await page.getByRole("button", { name: "Add line" }).click();
  const quantity = page.getByRole("textbox", { name: /^Quantity \(/ }).first();
  await expect(quantity).toHaveValue("40");

  // debounced save: typing settles into one save, shown as Saved; the value survives a reload
  await quantity.fill("45");
  await expect(page.locator('[data-save="saved"]').first()).toBeVisible({ timeout: 5_000 });
  await page.reload();
  await expect(page.getByRole("textbox", { name: /^Quantity \(/ }).first()).toHaveValue("45");

  // issue: the document freezes; quantities become read-only
  await page.getByTestId("challan-commands").getByRole("button", { name: "Issue challan" }).click();
  await expect(page.getByText("Challan issued").first()).toBeVisible();
  await expect(page.getByText("Issued challans can't be edited", { exact: false })).toBeVisible();
  await expect(page.getByRole("textbox", { name: /^Quantity \(/ })).toHaveCount(0);

  // PDF and CSV are real downloads from the API
  const id = challanPath.split("/").at(-1)!;
  const pdf = await page.request.get(`/api/v1/challans/challans/${id}/document.pdf`);
  expect(pdf.status()).toBe(200);
  expect(pdf.headers()["content-type"]).toContain("application/pdf");
  const csv = await page.request.get(`/api/v1/challans/challans/export.csv?q=${encodeURIComponent(challanNumber)}`);
  expect(csv.headers()["content-type"]).toContain("text/csv");
  expect(await csv.text()).toContain(challanNumber);

  // duplicate: a new draft with a new number and the same line
  await page.getByTestId("challan-commands").getByRole("button", { name: "Duplicate" }).click();
  await expect(page).not.toHaveURL(challanPath);
  await expect(page).toHaveURL(/\/operations\/challans\/[0-9a-f-]{36}$/);
  const copyNumber = ((await page.locator("header p.font-mono").first().textContent()) ?? "").trim();
  expect(copyNumber).toMatch(/^DC-\d{4}-\d{4,}$/);
  expect(copyNumber).not.toBe(challanNumber);
  await expect(page.getByRole("textbox", { name: /^Quantity \(/ }).first()).toHaveValue("45");
});

test("challan_print_preview: the print view shows the document without the shell", async ({ page }) => {
  test.skip(!challanPath, "needs the challan from the first test");
  await signInAs(page, "RAVI");
  const id = challanPath.split("/").at(-1)!;
  await page.goto(`/print/challans/${id}`);
  await expect(page.getByRole("heading", { level: 1, name: "Delivery challan" })).toBeVisible();
  await expect(page.getByText(challanNumber)).toBeVisible();
  for (const label of ["Delivered by", "Received by", "Authorised signatory"]) await expect(page.getByText(label)).toBeVisible();
  await expect(page.getByRole("button", { name: "Print" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: /primary/i })).toHaveCount(0);
});

test("challan_failed_save_shows_inline_retry: a failed quantity save stays on screen until retried", async ({ page }) => {
  await signInAs(page, "RAVI");
  await page.goto("/operations/challans/new");
  await page.getByRole("textbox", { name: "Destination name" }).fill("E2E walk-in customer");
  await page.getByRole("button", { name: "Create draft" }).click();
  await expect(page).toHaveURL(/\/operations\/challans\/[0-9a-f-]{36}$/);
  await page.getByRole("radio", { name: "Manual item" }).check();
  await page.getByRole("textbox", { name: "Item", exact: true }).fill("Pallet wrap");
  await page.getByRole("textbox", { name: "Quantity", exact: true }).fill("2");
  await page.getByRole("button", { name: "Add line" }).click();
  const quantity = page.getByRole("textbox", { name: /^Quantity \(/ }).first();
  await expect(quantity).toHaveValue("2");

  let fail = true;
  await page.route("**/api/v1/challans/challans/*/lines/*", async (route) => {
    if (fail && route.request().method() === "PATCH") {
      await route.fulfill({
        status: 503,
        contentType: "application/problem+json",
        body: JSON.stringify({ type: "about:blank", title: "Service unavailable", status: 503, code: "unavailable", detail: "Try again shortly" }),
      });
      return;
    }
    await route.continue();
  });
  await quantity.fill("3");
  const failed = page.locator('[data-save="failed"]').first();
  await expect(failed).toBeVisible({ timeout: 5_000 });
  await expect(failed).toContainText("Not saved");
  await page.waitForTimeout(1_500);
  await expect(failed).toBeVisible(); // never hidden on its own
  fail = false;
  await failed.getByRole("button", { name: "Retry" }).click();
  await expect(page.locator('[data-save="saved"]').first()).toBeVisible();
  await page.reload();
  await expect(page.getByRole("textbox", { name: /^Quantity \(/ }).first()).toHaveValue("3");
});

test("challan_admin_draft_delete: only an admin deletes a draft, and its number stays reserved", async ({ page }) => {
  await signInAs(page, "RAVI");
  await page.goto("/operations/challans/new");
  await page.getByRole("textbox", { name: "Destination name" }).fill("E2E draft to delete");
  await page.getByRole("button", { name: "Create draft" }).click();
  await expect(page).toHaveURL(/\/operations\/challans\/[0-9a-f-]{36}$/);
  const path = new URL(page.url()).pathname;
  await expect(page.getByTestId("challan-commands").getByRole("button", { name: "Delete draft" })).toHaveCount(0);

  await signInAs(page, "PRIYA");
  await page.goto(path);
  await page.getByTestId("challan-commands").getByRole("button", { name: "Delete draft" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Delete draft" }).click();
  await expect(page).toHaveURL(/\/operations\/challans$/);
  await page.goto(path);
  await expect(page.getByText("This draft was deleted. Its number stays reserved.")).toBeVisible();
});
