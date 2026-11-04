import { expect, test, type Page } from "@playwright/test";
import { loadWorld, onlyOnProjects, ref, signInAs } from "../support/world";

/**
 * Procure to pay through the UI (PLAN Slice 4; operations.md §5 and §14): inventory goes live on the e2e world (test
 * seam: WH-MAIN), Priya raises a purchase order to Kaveri for 20 sheets of LK-WB-1800 (QC-required, lot-tracked) and
 * submits it; Sahil approves (a different person), Priya marks it sent; Ravi receives all 20 with a lot code, the
 * receipt shows the QC inspection waiting; Ravi decides 18 accepted and 2 rejected with a reason; the purchase order
 * shows the accepted and rejected figures, and Ananya records the vendor bill, which matches against the accepted
 * quantity. Desktop only.
 */

test.describe.configure({ mode: "serial" });

let warehouseId = "";
let poPath = "";
let grnPath = "";

test.beforeAll(async ({ request }, info) => {
  onlyOnProjects("desktop");
  const origin = new URL(info.project.use.baseURL ?? "http://127.0.0.1").origin;
  const live = await request.post("/api/v1/_test/inventory/go-live", { headers: { Origin: origin } });
  expect(live.status(), "inventory go-live test seam").toBe(200);
  warehouseId = ((await live.json()) as { warehouse_id: string }).warehouse_id;
});

/** A JSON command with the session's CSRF token (the browser app sends the same headers). */
async function command(page: Page, path: string, body: unknown) {
  const bootstrap = await page.request.get("/api/v1/session/bootstrap");
  const csrf = ((await bootstrap.json()) as { csrf_token?: string | null }).csrf_token ?? "";
  const origin = new URL(page.url()).origin;
  const response = await page.request.post(path, {
    data: body,
    headers: { Origin: origin, "X-CSRF-Token": csrf, "Idempotency-Key": crypto.randomUUID() },
  });
  expect(response.status(), `${path} ${await response.text()}`).toBeLessThan(300);
  return response.json();
}

test("order: Priya raises and submits, Sahil approves, Priya sends it to the vendor", async ({ page, request }) => {
  const world = await loadWorld(request);
  const vendor = ref(world, "KAVERI");
  const board = ref(world, "WALNUT_BOARD");
  expect(vendor && board, "fixture refs KAVERI and WALNUT_BOARD").toBeTruthy();

  await signInAs(page, "PRIYA");
  await page.goto("/operations/purchasing/orders");
  const po = (await command(page, "/api/v1/procurement/purchase-orders", {
    vendor_party_id: vendor,
    warehouse_id: warehouseId,
    lines: [{ product_id: board, quantity: "20", unit_price: "4850.0000", price_override_reason: "Quoted by phone", expected_date: "2026-10-20" }],
  })) as { path: string };
  poPath = po.path;

  await page.goto(poPath);
  await expect(page.locator("header p.font-mono").first()).toHaveText(/^PO-\d{4}-\d{4,}$/);
  await page.getByRole("button", { name: "Submit for approval" }).click();
  await expect(page.getByText("Submitted for approval").first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve" })).toHaveCount(0); // the submitter never approves

  await signInAs(page, "SAHIL");
  await page.goto(poPath);
  await page.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByText("Purchase order approved").first()).toBeVisible();

  await signInAs(page, "PRIYA");
  await page.goto(poPath);
  await page.getByRole("button", { name: "Mark sent to vendor" }).click();
  await expect(page.getByText("Sent to vendor").first()).toBeVisible();
});

test("receipt: Ravi receives 20 sheets with a lot; they wait in QC", async ({ page }) => {
  test.skip(!poPath, "needs the purchase order from the first test");
  await signInAs(page, "RAVI");
  await page.goto(poPath);
  await page.getByRole("button", { name: "Receive goods" }).click();
  const panel = page.getByRole("region", { name: "Receive goods" });
  await expect(panel.getByRole("textbox", { name: /^Quantity/ }).first()).toHaveValue("20");
  await panel.getByRole("textbox", { name: "Lot code (required)" }).fill("WB-E2E-01");
  await panel.getByRole("textbox", { name: "Vendor challan number" }).fill("KTS/DC/771");
  await panel.getByRole("button", { name: "Receive goods" }).click();
  await expect(page).toHaveURL(/\/operations\/purchasing\/receipts\/[0-9a-f-]{36}$/);
  grnPath = new URL(page.url()).pathname;
  await expect(page.locator("header p.font-mono").first()).toHaveText(/^GRN-\d{4}-\d{4,}$/);
  await expect(page.getByText("Waiting").first()).toBeVisible();
});

test("inspection: Ravi accepts 18 and rejects 2 with a reason; the order shows both", async ({ page }) => {
  test.skip(!grnPath, "needs the receipt from the second test");
  await signInAs(page, "RAVI");
  await page.goto(grnPath);
  await page.getByRole("link", { name: /^QC-/ }).first().click();
  await expect(page).toHaveURL(/\/operations\/quality\/[0-9a-f-]{36}$/);
  await page.getByRole("textbox", { name: /^Accepted/ }).fill("18");
  await page.getByRole("textbox", { name: /^Rejected/ }).fill("2");
  await page.keyboard.press("Tab"); // number fields commit on blur
  await page.getByRole("button", { name: "Why rejected" }).click();
  await page.getByRole("option", { name: "Surface damage" }).click();
  await page.getByRole("textbox", { name: "Findings" }).fill("Two sheets with deep scratches on the face.");
  await page.getByRole("button", { name: "Record result" }).click();
  await expect(page.getByText("Result recorded").first()).toBeVisible();
  await expect(page.getByRole("region", { name: "Result" })).toContainText("Surface damage");

  await page.goto(poPath);
  const lines = page.getByRole("region", { name: "Lines" });
  await expect(lines).toContainText("18");
  await expect(lines).toContainText("2");
});

test("bill: Ananya records the vendor bill and it matches the accepted quantity", async ({ page }) => {
  test.skip(!poPath, "needs the purchase order");
  await signInAs(page, "ANANYA");
  await page.goto(poPath);
  const bills = page.getByRole("region", { name: "Vendor bills" });
  await bills.getByRole("button", { name: "Record vendor bill" }).click();
  await bills.getByRole("textbox", { name: "Bill number" }).fill("KTS/INV/2210");
  await bills.getByRole("group", { name: "Bill date" }).getByRole("spinbutton").first().click();
  await page.keyboard.type("14102026"); // en-IN segments: day, month, year
  // 18 × 4,850.0000: the line defaults (accepted, not yet billed; the order price) come from the order
  await bills.getByRole("textbox", { name: /^Subtotal as billed/ }).fill("87300");
  await bills.getByRole("textbox", { name: /^Total as billed/ }).fill("87300");
  await page.keyboard.press("Tab");
  await bills.getByRole("button", { name: "Record vendor bill" }).click();
  await expect(page.getByText("Bill recorded and matched").first()).toBeVisible();
  await expect(bills).toContainText("KTS/INV/2210");
  await expect(bills).toContainText("Matched");
});
