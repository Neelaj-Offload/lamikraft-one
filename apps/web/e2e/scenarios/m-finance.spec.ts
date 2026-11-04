import { expect, test, type Page } from "@playwright/test";
import { addCatalogLine, chooseFromCombobox, newDraftQuote } from "../support/quotes";
import { onlyOnProjects, signInAs } from "../support/world";

/**
 * Scenario M (finance part) through the UI (PLAN Slice 5): inventory goes live on the e2e world (test seam); Meera
 * wins and converts a quote and Ravi issues a delivery challan for it (API set-up, the same commands the UI sends).
 * Ananya sees the challan suggested on the Finance overview, drafts the invoice (labelled "Draft — not valid for
 * trade", the issue check listing its blockers) and submits it; Sahil approves (the drafter cannot); Ananya's issue
 * is refused with the reasons listed and no number; she records a receipt; Accounting sync says Demo — not connected.
 * Desktop only.
 */

test.describe.configure({ mode: "serial" });

let invoicePath = "";

test.beforeAll(async ({ request }, info) => {
  onlyOnProjects("desktop");
  const origin = new URL(info.project.use.baseURL ?? "http://127.0.0.1").origin;
  const live = await request.post("/api/v1/_test/inventory/go-live", { headers: { Origin: origin } });
  expect(live.status(), "inventory go-live test seam").toBe(200);
});

async function command(page: Page, path: string, body: unknown) {
  const bootstrap = await page.request.get("/api/v1/session/bootstrap");
  const csrf = ((await bootstrap.json()) as { csrf_token?: string | null }).csrf_token ?? "";
  const origin = new URL(page.url() === "about:blank" ? (test.info().project.use.baseURL ?? "http://127.0.0.1") : page.url()).origin;
  const response = await page.request.post(path, {
    data: body,
    headers: { Origin: origin, "X-CSRF-Token": csrf, "Idempotency-Key": crypto.randomUUID() },
  });
  expect(response.status(), `${path} ${await response.text()}`).toBeLessThan(300);
  return response.json();
}

async function version(page: Page, path: string): Promise<number> {
  return ((await (await page.request.get(path)).json()) as { version: number }).version;
}

test("set-up: a won quote becomes an order and Ravi issues its delivery challan", async ({ page }) => {
  await signInAs(page, "MEERA");
  const quotePath = await newDraftQuote(page, "Nordhaus");
  await addCatalogLine(page, "LK-OT-0450", /LK-OT-0450/, "240");
  const quoteId = quotePath.split("/").at(-1)!;
  for (const action of ["mark_sent", "mark_won"]) {
    await command(page, `/api/v1/sales/quotes/${quoteId}/transitions`, { action, expected_version: await version(page, `/api/v1/sales/quotes/${quoteId}`) });
  }
  const converted = (await command(page, "/api/v1/orders/sales-orders/convert", { quote_id: quoteId })) as { order: { id: string } };
  const orderId = converted.order.id;
  await command(page, `/api/v1/orders/sales-orders/${orderId}/transitions`, {
    action: "confirm",
    expected_version: await version(page, `/api/v1/orders/sales-orders/${orderId}`),
  });

  await signInAs(page, "RAVI");
  await page.goto("/operations");
  const created = (await command(page, `/api/v1/orders/sales-orders/${orderId}/challans`, {})) as { challan_id: string };
  await command(page, `/api/v1/challans/challans/${created.challan_id}/transitions`, {
    action: "issue",
    expected_version: await version(page, `/api/v1/challans/challans/${created.challan_id}`),
  });
});

test("Ananya drafts the invoice from the suggestion: labelled, blockers listed, submitted", async ({ page }) => {
  await signInAs(page, "ANANYA");
  await page.goto("/finance");
  await expect(page.getByRole("heading", { name: "Why invoices cannot be issued yet" })).toBeVisible();
  await expect(page.locator("main")).toContainText("Not connected (demo)");
  const draft = page.getByRole("button", { name: "Draft invoice" }).first();
  await expect(async () => {
    await page.reload();
    await expect(draft).toBeVisible({ timeout: 2_000 });
  }).toPass({ timeout: 60_000 }); // the suggestion arrives through the worker
  await draft.click();
  await expect(page).toHaveURL(/\/finance\/invoices\/[0-9a-f-]{36}$/);
  invoicePath = new URL(page.url()).pathname;
  await expect(page.locator("main")).toContainText("Draft — not valid for trade");
  await expect(page.getByRole("region", { name: "Issue check" })).toContainText("The company's legal name, address or GSTIN is not set.");
  await expect(page.getByRole("region", { name: "Issue check" })).toContainText("No tax profile is chosen");
  await page.getByRole("button", { name: "Submit for approval" }).click();
  await expect(page.getByText("Submitted for approval").first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve" })).toHaveCount(0); // never the drafter
});

test("Sahil approves; Ananya's issue is refused with the reasons and no number", async ({ page }) => {
  test.skip(!invoicePath, "needs the draft from the previous test");
  await signInAs(page, "SAHIL");
  await page.goto(invoicePath);
  await page.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByText("Approved").first()).toBeVisible();

  await signInAs(page, "ANANYA");
  await page.goto(invoicePath);
  await page.getByRole("button", { name: "Issue" }).click();
  await expect(page.getByText("Not issued: the reasons are listed on the document").first()).toBeVisible();
  await expect(page.locator("header p.font-mono").first()).toHaveText(/^Draft FD-\d{5}$/);
  await expect(page.getByRole("region", { name: "Issue check" })).toContainText("No tax profile is chosen");
  await expect(page.getByRole("region", { name: "History" })).toContainText("Issue refused");
  const pdf = await page.request.get(`/api/v1/finance/invoices/${invoicePath.split("/").at(-1)}/document.pdf`);
  expect(pdf.status()).toBe(200);
  expect(pdf.headers()["content-type"]).toContain("application/pdf");
});

test("Ananya records a receipt; accounting sync is Demo — not connected", async ({ page }) => {
  await signInAs(page, "ANANYA");
  await page.goto("/finance/receipts");
  await page.getByRole("button", { name: "Record receipt" }).click();
  const dialog = page.getByRole("dialog", { name: "Record a receipt" });
  await chooseFromCombobox(page, dialog.getByRole("combobox", { name: "Customer" }), "Nordhaus", /Nordhaus/);
  const amount = dialog.getByRole("textbox", { name: /^Amount/ });
  await amount.fill("500");
  await amount.press("Tab");
  await dialog.getByRole("group", { name: "Received on" }).getByRole("spinbutton").first().click();
  await page.keyboard.type("12102026"); // en-IN: day, month, year (D0)
  await dialog.getByRole("button", { name: "Record receipt" }).click();
  await expect(page).toHaveURL(/\/finance\/receipts\/[0-9a-f-]{36}$/);
  await expect(page.locator("header p.font-mono").first()).toHaveText(/^RCPT-\d{4}-\d{2}-\d{4}$/);
  await expect(page.getByText("This customer has no open invoice in this currency.")).toBeVisible();

  await page.goto("/finance/accounting-sync");
  await expect(page.locator("main")).toContainText("Demo — not connected");
  await expect(page.locator("main")).toContainText("No accounting system is connected.");
});
