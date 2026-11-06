import { expect, test, type Page } from "@playwright/test";
import { shoot } from "../support/evidence";
import { fact, loadWorld, onlyOnProjects, ref, signInAs, type World } from "../support/world";

/**
 * Slice-5 new capabilities through the UI (capabilities report integrator request 4), on the e2e world seeded at
 * `--slice 5`:
 * - offcut reuse: Deepa records a measured walnut offcut on WO-2026-0001 (API set-up, the command the work-order
 *   screen sends; the production journey has put the work order in progress), creates a cut plan whose panel fits
 *   it, chooses the offcut on the plan ("Offcuts to use first") and calculates: the layout cuts one board from it;
 * - sample lineage: Meera requests a sample for Nordhaus and drafts a sample challan for it (API set-up), links the
 *   challan on the sample; Ravi issues the challan and the sample becomes dispatched by itself (the
 *   `sales.sample_dispatch` consumer on the worker; the challan event carries no sample id); the lineage lists it;
 * - what-if: Deepa compares today's answer for 8 walnut panel sets with one where 8 walnut sheets are added.
 * Desktop only. Sorted after `production/work-order-journey.spec.ts`.
 */

test.describe.configure({ mode: "serial" });

let world: World;

test.beforeAll(async ({ request }) => {
  onlyOnProjects("desktop");
  world = await loadWorld(request);
});

function fixture(key: string): string {
  const value = ref(world, key);
  expect(value, `fixture ref ${key} (is the e2e world seeded at --slice 5?)`).toBeTruthy();
  return value!;
}

async function send(page: Page, method: "post" | "put", path: string, body: unknown) {
  const bootstrap = await page.request.get("/api/v1/session/bootstrap");
  const csrf = ((await bootstrap.json()) as { csrf_token?: string | null }).csrf_token ?? "";
  const origin = new URL(test.info().project.use.baseURL ?? "http://127.0.0.1").origin;
  const response = await page.request[method](path, {
    data: body,
    headers: { Origin: origin, "X-CSRF-Token": csrf, "Idempotency-Key": crypto.randomUUID() },
  });
  expect(response.status(), `${method.toUpperCase()} ${path} ${await response.text()}`).toBeLessThan(300);
  return response.json();
}

async function read<T>(page: Page, path: string): Promise<T> {
  const response = await page.request.get(path);
  expect(response.status(), `GET ${path}`).toBe(200);
  return (await response.json()) as T;
}

test("offcut reuse: a plan chooses Deepa's measured offcut and cuts a board from it", async ({ page }) => {
  test.setTimeout(120_000);
  const number = fact(world, "work_orders", "PANEL_SETS");
  const woId = (number ? ref(world, number) : null) ?? fixture("WO_PANEL_SETS");
  await signInAs(page, "DEEPA");
  type Wo = { version: number; materials: { id: string; is_sheet_material: boolean }[] };
  const wo = await read<Wo>(page, `/api/v1/production/work-orders/${woId}`);
  const sheet = wo.materials.find((m) => m.is_sheet_material);
  expect(sheet, "WO-2026-0001 has a sheet material").toBeTruthy();
  await send(page, "post", `/api/v1/production/work-orders/${woId}/offcuts`, {
    expected_version: wo.version,
    material_id: sheet!.id,
    length_mm: "1180",
    width_mm: "610",
    thickness_mm: "18",
    grain_axis: "length",
    lot_code: "OC-E2E-01",
  });
  const plan = (await send(page, "post", "/api/v1/cutting/plans", {
    name: "Walnut doors from an offcut (e2e)",
    items: [
      { sku: "WD-PANEL", decor: "0457", thickness_mm: "18", length_mm: "1100", width_mm: "580", quantity: 1 },
      { sku: "WD-SHELF", decor: "0457", thickness_mm: "18", length_mm: "720", width_mm: "560", quantity: 5 },
    ],
  })) as { id: string };

  await page.goto(`/operations/cutting/${plan.id}`);
  const offcuts = page.getByRole("region", { name: "Offcuts to use first" });
  await expect(offcuts).toContainText("No offcut chosen");
  await offcuts.getByRole("button", { name: "Choose offcuts" }).click();
  const choice = offcuts.getByRole("checkbox", { name: "Use OC-E2E-01" });
  await choice.press("Space");
  await expect(choice).toBeChecked();
  await offcuts.getByRole("button", { name: "Save offcut choice" }).click();
  await expect(page.getByText("Offcut choice saved. Calculate again to use it.").first()).toBeVisible();
  await expect(offcuts.getByRole("list", { name: "Offcuts to use first" })).toContainText("OC-E2E-01");

  await page.getByRole("button", { name: "Calculate layout" }).first().click();
  await expect(page.getByText("From offcuts").first()).toBeVisible({ timeout: 30_000 });
  await expect(offcuts).toContainText("Used in the layout");
  await shoot(page, "cut-plan-from-offcut", `/operations/cutting/${plan.id}`); // checkpoint-6 evidence (cp6 only)
});

test("sample lineage: the linked challan's issue dispatches the sample", async ({ page }) => {
  test.setTimeout(120_000);
  await signInAs(page, "MEERA");
  const sample = (await send(page, "post", "/api/v1/sales/samples", {
    party_id: fixture("NORDHAUS"),
    description: "Oak tray finish sample (e2e)",
    quantity: "2",
    product_id: fixture("OAK_TRAY"),
  })) as { id: string };
  const challan = (await send(page, "post", "/api/v1/challans/challans", {
    challan_type: "sample",
    party_id: fixture("NORDHAUS"),
    source_warehouse_id: ref(world, "WH_MAIN"),
    lines: [{ line_type: "catalog", product_id: fixture("OAK_TRAY"), quantity: "2" }],
  })) as { id: string; challan_number?: string | null };

  await page.goto(`/sales/samples/${sample.id}`);
  const lineage = page.getByRole("region", { name: "Lineage" });
  await expect(lineage).toContainText("Not linked yet");
  await lineage.getByRole("button", { name: "Link a delivery challan" }).click();
  const dialog = page.getByRole("dialog", { name: "Delivery challan for this sample" });
  await dialog.getByRole("button", { name: /Challan/ }).first().click();
  await page.getByRole("option").first().click();
  await dialog.getByRole("button", { name: "Link challan" }).click();
  await expect(page.getByText("Challan linked").first()).toBeVisible();

  await signInAs(page, "RAVI");
  const current = await read<{ version: number }>(page, `/api/v1/challans/challans/${challan.id}`);
  await send(page, "post", `/api/v1/challans/challans/${challan.id}/transitions`, { action: "issue", expected_version: current.version });

  await signInAs(page, "MEERA");
  await expect
    .poll(async () => (await read<{ status: string }>(page, `/api/v1/sales/samples/${sample.id}`)).status, { timeout: 30_000 })
    .toBe("dispatched");
  await page.goto(`/sales/samples/${sample.id}`);
  await expect(page.getByRole("region", { name: "Lineage" })).toContainText("Delivery challan");
  await expect(page.getByRole("region", { name: "Lineage" })).not.toContainText("Not linked yet");
  await shoot(page, "sample-lineage", `/sales/samples/${sample.id}`); // checkpoint-6 evidence (cp6 only)
});

test("what-if: Deepa compares today with 8 more walnut sheets", async ({ page }) => {
  test.setTimeout(120_000);
  await signInAs(page, "DEEPA");
  await page.goto("/operations/production/what-if");
  await expect(page.getByRole("heading", { name: "What-if", level: 1 })).toBeVisible();
  await page.getByRole("button", { name: /^Product/ }).first().click();
  await page.getByRole("option", { name: /LK-WP-0001/ }).first().click();
  const quantity = page.getByRole("textbox", { name: /^Quantity/ }).first();
  await quantity.fill("8");
  await quantity.press("Tab");
  await page.getByRole("group", { name: /^Needed by/ }).first().getByRole("spinbutton").first().click();
  await page.keyboard.type("30112026"); // en-IN: day, month, year

  await page.getByRole("button", { name: "Add a stock change" }).click();
  const stockProduct = page.getByRole("combobox", { name: /^Component or product/ }).first();
  await stockProduct.fill("LK-WB");
  await page.getByRole("option", { name: /LK-WB-1800/ }).first().click();
  const delta = page.getByRole("textbox", { name: /^Change in stock/ }).first();
  await delta.fill("8");
  await delta.press("Tab");

  await page.getByRole("button", { name: "Run the simulation" }).click();
  const results = page.getByRole("region", { name: "Today and with the change" });
  await expect(results).toContainText("Today", { timeout: 30_000 });
  await expect(results).toContainText("With the change");
  await expect(results).toContainText(/The answer changes|Same answer/);
  await expect(results).toContainText("Read-only");
});
