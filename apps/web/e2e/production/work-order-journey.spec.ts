import { expect, test, type Page } from "@playwright/test";
import { fact, loadWorld, onlyOnProjects, ref, signInAs, type World } from "../support/world";

/**
 * Production journey through the UI (Slice-4 merge; production report integrator request 10), on the e2e world
 * seeded at `--slice 4`: Deepa sees WO-2026-0001 (8 walnut panel sets, 48 sheets of LK-WB-1800 needed, 40 reserved)
 * blocked by the shortage; Ravi receives 8 sheets on the late PO-2026-0001 and QC accepts them, and the work order
 * unblocks by itself (the `production.material_retry` consumer on the worker); Deepa issues, consumes and posts
 * output, each one stock posting on the work order; a new BOM version is approved by a second person (Sahil), never
 * its author; the capacity page lists the work centres. Desktop only. This file sorts before
 * `scenarios/p-procure-to-pay.spec.ts`, whose accepted sheets would otherwise unblock the work order first.
 */

test.describe.configure({ mode: "serial" });

let world: World;
let woPath = "";

test.beforeAll(async ({ request }) => {
  onlyOnProjects("desktop");
  world = await loadWorld(request);
});

function id(name: string, key: string, fixtureRef: string): string {
  const number = fact(world, name, key);
  const value = (number ? ref(world, number) : null) ?? ref(world, fixtureRef);
  expect(value, `fixture ${name}.${key} (is the e2e world seeded at --slice 4?)`).toBeTruthy();
  return value!;
}

async function workOrder(page: Page, woId: string): Promise<{ is_blocked: boolean; version: number }> {
  const response = await page.request.get(`/api/v1/production/work-orders/${woId}`);
  expect(response.status()).toBe(200);
  return (await response.json()) as { is_blocked: boolean; version: number };
}

test("blocked: Deepa sees WO-2026-0001 blocked by the walnut shortage", async ({ page }) => {
  const woId = id("work_orders", "PANEL_SETS", "WO_PANEL_SETS");
  woPath = `/operations/production/work-orders/${woId}`;
  await signInAs(page, "DEEPA");
  await page.goto("/operations/production/work-orders");
  await page.getByRole("link", { name: "WO-2026-0001" }).first().click();
  await expect(page).toHaveURL(new RegExp(`${woPath}$`));
  await expect(page.getByText("Blocked by a material shortage").first()).toBeVisible();
  const materials = page.getByRole("region", { name: "Materials" });
  await expect(materials).toContainText("LK-WB-1800");
  await expect(materials).toContainText("Short");
});

test("supply: Ravi receives 8 sheets on PO-2026-0001, QC accepts them, and the work order unblocks", async ({ page }) => {
  test.skip(!woPath, "needs the work order from the first test");
  const poId = id("purchase_orders", "KAVERI_WALNUT", "PO_KAVERI");
  await signInAs(page, "RAVI");
  await page.goto(`/operations/purchasing/orders/${poId}`);
  await expect(page.locator("header p.font-mono").first()).toHaveText("PO-2026-0001");
  await page.getByRole("button", { name: "Receive goods" }).click();
  const panel = page.getByRole("region", { name: "Receive goods" });
  await panel.getByRole("textbox", { name: /^Quantity/ }).first().fill("8");
  await panel.getByRole("textbox", { name: "Lot code (required)" }).fill("WB-E2E-PRD");
  await panel.getByRole("textbox", { name: "Vendor challan number" }).fill("KTS/DC/812");
  await page.keyboard.press("Tab"); // number fields commit on blur
  await panel.getByRole("button", { name: "Receive goods" }).click();
  await expect(page).toHaveURL(/\/operations\/purchasing\/receipts\/[0-9a-f-]{36}$/);
  await page.getByRole("link", { name: /^QC-/ }).first().click();
  await expect(page).toHaveURL(/\/operations\/quality\/[0-9a-f-]{36}$/);
  await page.getByRole("textbox", { name: /^Accepted/ }).fill("8");
  await page.getByRole("textbox", { name: /^Rejected/ }).fill("0");
  await page.keyboard.press("Tab");
  await page.getByRole("button", { name: "Record result" }).click();
  await expect(page.getByText("Result recorded").first()).toBeVisible();

  // the accepted sheets post QC hold -> stock; the worker's material retry reserves them and unblocks the work order
  await signInAs(page, "DEEPA");
  const woId = woPath.split("/").at(-1)!;
  await expect.poll(async () => (await workOrder(page, woId)).is_blocked, { timeout: 30_000 }).toBe(false);
  await page.goto(woPath);
  await expect(page.getByText("Blocked by a material shortage")).toHaveCount(0);
});

test("work: Deepa issues, consumes and posts output; each is one stock posting", async ({ page }) => {
  test.skip(!woPath, "needs the work order from the first test");
  await signInAs(page, "DEEPA");
  await page.goto(woPath);

  await page.getByRole("button", { name: "Issue", exact: true }).first().click();
  const issue = page.getByRole("dialog", { name: "Issue material" });
  await issue.getByRole("textbox", { name: /^Quantity of LK-WB-1800/ }).fill("6");
  await page.keyboard.press("Tab");
  await issue.getByRole("button", { name: "Issue", exact: true }).click();
  await expect(page.getByText("Material issued to work in progress").first()).toBeVisible();

  await page.getByRole("button", { name: "Consume", exact: true }).first().click();
  const consume = page.getByRole("dialog", { name: "Consume" });
  await expect(consume.getByRole("textbox", { name: /^Quantity of LK-WB-1800/ })).toHaveValue("6");
  await consume.getByRole("button", { name: "Consume", exact: true }).click();
  await expect(page.getByText("Material consumed").first()).toBeVisible();

  await page.getByRole("button", { name: "Post output", exact: true }).first().click();
  const output = page.getByRole("dialog", { name: "Report output" });
  await output.getByRole("textbox", { name: /^Good quantity/ }).fill("1");
  await page.keyboard.press("Tab");
  await output.getByRole("button", { name: "Post output", exact: true }).click();
  await expect(page.getByText("Output posted to stock").first()).toBeVisible();

  const postings = page.getByRole("region", { name: "Stock postings" });
  for (const kind of ["Issue", "Consume", "Output"]) await expect(postings).toContainText(kind);
});

test("masters: a new BOM version is approved by someone other than its author", async ({ page }) => {
  const bomId = ref(world, "BOM_PANEL_SET");
  expect(bomId, "fixture BOM_PANEL_SET").toBeTruthy();
  await signInAs(page, "DEEPA");
  await page.goto(`/operations/production/boms/${bomId}`);
  await page.getByRole("button", { name: "New version from this one" }).click();
  await expect(page.getByText("Draft version created").first()).toBeVisible();
  await expect(page).not.toHaveURL(new RegExp(`${bomId}$`));
  const draftPath = new URL(page.url()).pathname;
  await expect(page.getByText("You wrote this version, so someone else approves it.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve" })).toHaveCount(0);

  await signInAs(page, "SAHIL");
  await page.goto(draftPath);
  await page.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByText("Version approved").first()).toBeVisible();

  await page.goto("/operations/production/capacity");
  await expect(page.getByRole("main")).toContainText("PANEL-SAW");
});
