import { mkdirSync } from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { fact, loadWorld, onlyOnProjects, ref, signInAs, type PersonKey, type World } from "./support/world";

/**
 * Checkpoint-5 evidence (docs/evidence/checkpoint-5/): the screens the Slice-4 lanes added (sales orders, inventory,
 * reservations, production, purchasing, quality, dispatch) at 1440 and 390 px, light and dark, on the --slice 4 demo
 * world. Opt-in, after a full run (it only reads):
 * `LK_E2E_EVIDENCE=cp5 npm run test:e2e -- --no-build e2e/evidence-cp5.spec.ts --project=desktop`.
 */

const OUT = path.resolve(__dirname, "../../../docs/evidence/checkpoint-5");
const WIDTHS = [
  { name: "1440", width: 1440, height: 900 },
  { name: "390", width: 390, height: 844 },
] as const;
const THEMES = ["light", "dark"] as const;

test.skip(process.env.LK_E2E_EVIDENCE !== "cp5", "checkpoint-5 evidence runs only with LK_E2E_EVIDENCE=cp5");
test.describe.configure({ mode: "serial" });

let world: World;

test.beforeAll(async ({ request }) => {
  onlyOnProjects("desktop");
  mkdirSync(OUT, { recursive: true });
  world = await loadWorld(request);
});

const byNumber = (name: string, key: string, fallback: string) => {
  const number = fact(world, name, key);
  return (number ? ref(world, number) : null) ?? ref(world, fallback);
};

type Shot = { name: string; person: PersonKey; url: () => string | null };

const SHOTS: readonly Shot[] = [
  { name: "operations-overview", person: "RAVI", url: () => "/operations" },
  { name: "sales-orders", person: "MEERA", url: () => "/sales/orders" },
  { name: "inventory-stock", person: "RAVI", url: () => "/operations/inventory" },
  { name: "inventory-movements", person: "RAVI", url: () => "/operations/inventory/movements" },
  { name: "reservations-shortages", person: "RAVI", url: () => "/operations/reservations" },
  { name: "work-orders", person: "DEEPA", url: () => "/operations/production/work-orders" },
  {
    name: "work-order",
    person: "DEEPA",
    url: () => {
      const id = byNumber("work_orders", "PANEL_SETS", "WO_PANEL_SETS");
      return id ? `/operations/production/work-orders/${id}` : null;
    },
  },
  { name: "bom", person: "DEEPA", url: () => (ref(world, "BOM_PANEL_SET") ? `/operations/production/boms/${ref(world, "BOM_PANEL_SET")}` : null) },
  { name: "capacity", person: "DEEPA", url: () => "/operations/production/capacity" },
  { name: "purchase-orders", person: "PRIYA", url: () => "/operations/purchasing/orders" },
  {
    name: "purchase-order",
    person: "PRIYA",
    url: () => {
      const id = byNumber("purchase_orders", "KAVERI_WALNUT", "PO_KAVERI");
      return id ? `/operations/purchasing/orders/${id}` : null;
    },
  },
  { name: "quality", person: "RAVI", url: () => "/operations/quality?status=all" },
  { name: "dispatch", person: "RAVI", url: () => "/operations/dispatch" },
];

async function open(page: Page, person: PersonKey, theme: (typeof THEMES)[number], width: (typeof WIDTHS)[number], url: string) {
  await signInAs(page, person);
  await page.context().addCookies([{ name: "lk_ui", value: `theme=${theme}&motion=reduced`, url: test.info().project.use.baseURL! }]);
  await page.setViewportSize({ width: width.width, height: width.height });
  await page.goto(url);
  await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
  await expect(page.getByRole("main")).toBeVisible();
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(800);
}

for (const theme of THEMES) {
  for (const width of WIDTHS) {
    test(`checkpoint-5 evidence ${width.name} ${theme}`, async ({ page }) => {
      test.setTimeout(300_000);
      for (const shot of SHOTS) {
        const url = shot.url();
        if (!url) continue;
        await open(page, shot.person, theme, width, url);
        await page.screenshot({ path: path.join(OUT, `${shot.name}-${width.name}-${theme}.png`), fullPage: false });
      }
    });
  }
}
