import { expect, test, type Page } from "@playwright/test";
import { addCatalogLine, newDraftQuote } from "../support/quotes";
import { onlyOnProjects, signInAs } from "../support/world";

/**
 * Scenario I through the UI (PLAN Slice 4; operations.md §14 `order-fulfilment.spec.ts::convert_reserve_dispatch`):
 * inventory goes live on the e2e world (test seam: WH-MAIN, the approved opening batch, challan postings on); Meera
 * wins a quote and converts it once (a second conversion opens the same order), confirms and reserves; Ravi creates
 * the delivery challan from the order, cuts it to a partial quantity, issues it (one stock movement) and sees the
 * issued challan read-only, the order line partly delivered, the ledger entry and the stock figure. Desktop only.
 */

test.describe.configure({ mode: "serial" });

let quotePath = "";
let orderPath = "";

test.beforeAll(async ({ request }, info) => {
  onlyOnProjects("desktop");
  const origin = new URL(info.project.use.baseURL ?? "http://127.0.0.1").origin;
  const live = await request.post("/api/v1/_test/inventory/go-live", { headers: { Origin: origin } });
  expect(live.status(), "inventory go-live test seam").toBe(200);
});

/** A JSON command with the session's CSRF token (the browser app sends the same headers). */
async function command(page: Page, path: string, body: unknown) {
  const cookies = await page.context().cookies();
  const csrf = cookies.find((c) => c.name === "lk_csrf")?.value ?? "";
  const origin = new URL(page.url()).origin;
  const response = await page.request.post(path, {
    data: body,
    headers: { Origin: origin, "X-CSRF-Token": csrf, "Idempotency-Key": crypto.randomUUID() },
  });
  expect(response.status(), `${path} ${await response.text()}`).toBeLessThan(300);
  return response.json();
}

async function quoteVersion(page: Page, quoteId: string): Promise<number> {
  const response = await page.request.get(`/api/v1/sales/quotes/${quoteId}`);
  return ((await response.json()) as { version: number }).version;
}

test("convert_reserve_dispatch_partial: a won quote becomes one order, reserved and partly delivered with one movement", async ({ page }) => {
  await signInAs(page, "MEERA");
  quotePath = await newDraftQuote(page, "Nordhaus");
  await addCatalogLine(page, "LK-OT-0450", /LK-OT-0450/, "240");
  const quoteId = quotePath.split("/").at(-1)!;
  for (const action of ["mark_sent", "mark_won"]) {
    await command(page, `/api/v1/sales/quotes/${quoteId}/transitions`, { action, expected_version: await quoteVersion(page, quoteId) });
  }

  // accept once: Convert to order, then the quote links to the same order
  await page.goto(quotePath);
  await page.getByRole("button", { name: "Convert to order" }).click();
  await expect(page).toHaveURL(/\/sales\/orders\/[0-9a-f-]{36}$/);
  orderPath = new URL(page.url()).pathname;
  await expect(page.locator("header p.font-mono").first()).toHaveText(/^SO-\d{4}-\d{4,}$/);
  await page.goto(quotePath);
  await expect(page.getByRole("link", { name: /^Open SO-/ })).toHaveAttribute("href", orderPath);

  // confirm and reserve: 240 of 600 on hand
  await page.goto(orderPath);
  await page.getByRole("button", { name: "Confirm order" }).click();
  await expect(page.getByText("Order confirmed").first()).toBeVisible();
  await page.getByRole("button", { name: "Reserve stock" }).click();
  await expect(page.getByText(/Reserved 1 line/).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Reserve stock" })).toHaveCount(1); // still offered: capability-driven
  await expect(page.getByRole("region", { name: "Reservations" })).toContainText("WH-MAIN");
});

test("dispatch: Ravi delivers 100 of 240 on one challan; the issue moves stock once", async ({ page }) => {
  test.skip(!orderPath, "needs the order from the first test");
  await signInAs(page, "RAVI");
  await page.goto(orderPath);
  await page.getByRole("button", { name: "Create delivery challan" }).click();
  await expect(page).toHaveURL(/\/operations\/challans\/[0-9a-f-]{36}$/);
  const quantity = page.getByRole("textbox", { name: /^Quantity \(/ }).first();
  await expect(quantity).toHaveValue("240");
  await quantity.fill("100");
  await expect(page.locator('[data-save="saved"]').first()).toBeVisible({ timeout: 5_000 });
  await page.getByTestId("challan-commands").getByRole("button", { name: "Issue challan" }).click();
  await expect(page.getByText("Challan issued").first()).toBeVisible();
  await expect(page.getByRole("textbox", { name: /^Quantity \(/ })).toHaveCount(0); // issued challans are read-only
  const challanNumber = ((await page.locator("header p.font-mono").first().textContent()) ?? "").trim();

  // the order line: delivered 100, remaining 140
  await page.goto(orderPath);
  const lines = page.getByRole("region", { name: "Lines" });
  await expect(lines).toContainText("100");
  await expect(lines).toContainText("140");
  await expect(page.getByRole("region", { name: "Delivery documents" })).toContainText(challanNumber);

  // the ledger and the projection: one movement from the challan, on hand 600 -> 500
  await page.goto("/operations/inventory/movements");
  await expect(page.getByRole("link", { name: challanNumber })).toHaveCount(1);
  await page.goto("/operations/inventory?q=LK-OT-0450");
  await expect(page.getByText("LK-OT-0450").first()).toBeVisible();
  await expect(page.locator("main")).toContainText("500");
});
