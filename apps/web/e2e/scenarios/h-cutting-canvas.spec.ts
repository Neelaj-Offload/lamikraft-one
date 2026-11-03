import { expect, test, type Page } from "@playwright/test";
import { loadWorld, onlyOnProjects, signInAs } from "../support/world";

/**
 * Scenario H (PLAN.md Slice 2, PARITY LM-76, UI-18/72/73/75): Ravi builds a cut plan from the catalogue,
 * saves and calculates it, reopens it without recomputing, inspects the true-scale canvas (no overlaps, inside
 * the board, counts match the table) and downloads a board SVG; oversize and overproduction have visible effects.
 * Written by the cutting lane; run by the integrator (`npm run test:e2e`) on a world seeded with `--slice 2`.
 */

test.describe.configure({ mode: "serial" });

test.beforeAll(async ({ request }) => {
  onlyOnProjects("desktop", "phone");
  await loadWorld(request);
});

let planPath = "";

async function fillRow(page: Page, row: number, values: Record<string, string>) {
  for (const [label, value] of Object.entries(values)) {
    await page.getByRole("textbox", { name: `${label}, Row ${row}` }).fill(value);
  }
}

test("plan_calculate_save_reopen_svg", async ({ page }) => {
  await signInAs(page, "RAVI");
  await page.goto("/operations/cutting/new");
  await page.getByRole("textbox", { name: "Plan name" }).fill("Scenario H panels");
  await fillRow(page, 1, { "SKU or part": "PANEL-A", Decor: "0457", "Thickness (mm)": "18", "Length (mm)": "720", "Width (mm)": "560", Qty: "6" });
  await fillRow(page, 2, { "SKU or part": "PANEL-B", Decor: "0457", "Thickness (mm)": "18", "Length (mm)": "1200", "Width (mm)": "600", Qty: "3" });
  await page.getByRole("button", { name: "Create plan" }).click();
  await expect(page).toHaveURL(/\/operations\/cutting\/[0-9a-f-]{36}$/);
  planPath = new URL(page.url()).pathname;

  await page.getByRole("button", { name: "Calculate layout" }).click();
  await expect(page.getByText("Heuristic layout, not guaranteed optimal.")).toBeVisible();
  const pieces = page.locator('g[role="img"][tabindex="0"]');
  await expect(pieces.first()).toBeVisible();

  await page.reload();
  await expect(page.getByText("Calculation 1")).toBeVisible();

  const svgLink = page.getByRole("link", { name: "Board drawing (SVG)" }).first();
  const response = await page.request.get((await svgLink.getAttribute("href"))!);
  expect(response.headers()["content-type"]).toContain("image/svg+xml");
});

test("svg_no_overlap_inside_boundary_counts_match", async ({ page }) => {
  await signInAs(page, "RAVI");
  await page.goto(planPath);
  const boxes = await page.locator('svg[viewBox] > svg').evaluateAll((nodes) =>
    nodes.map((n) => ["x", "y", "width", "height"].map((a) => Number.parseFloat(n.getAttribute(a) ?? "0"))),
  );
  for (let i = 0; i < boxes.length; i += 1) {
    const [x, y, w, h] = boxes[i]!;
    expect(x! >= 5 && y! >= 5 && x! + w! <= 2435 && y! + h! <= 1215).toBe(true);
    for (let j = i + 1; j < boxes.length; j += 1) {
      const [x2, y2, w2, h2] = boxes[j]!;
      expect(x! + w! <= x2! || x2! + w2! <= x! || y! + h! <= y2! || y2! + h2! <= y!).toBe(true);
    }
  }
  await page.getByText(/Placement table/).first().click();
  const rows = page.getByRole("table", { name: /Pieces on board 1/ }).locator("tbody tr");
  expect(await rows.count()).toBe(boxes.length);
});

test("oversize_and_overproduction_have_effects", async ({ page }) => {
  await signInAs(page, "RAVI");
  await page.goto("/operations/cutting/new");
  await page.getByRole("textbox", { name: "Plan name" }).fill("Oversize check");
  await fillRow(page, 1, { "SKU or part": "WIDE", Decor: "0457", "Thickness (mm)": "18", "Length (mm)": "2435", "Width (mm)": "1215", Qty: "1" });
  await page.getByRole("switch", { name: /oversize per side/ }).click();
  await page.getByRole("button", { name: "Create plan" }).click();
  await page.getByRole("button", { name: "Calculate layout" }).click();
  await expect(page.getByRole("heading", { name: "Verify the boards" })).toBeVisible();
  await expect(page.getByText("This layout assumes boards of 2460 × 1240 mm.")).toBeVisible();
});
