import { mkdirSync } from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { loadWorld, onlyOnProjects, ref, signInAs, type PersonKey, type World } from "./support/world";

/**
 * Checkpoint-3 evidence (docs/evidence/checkpoint-3/): the screens Slice 2 added or changed, at 1440 and 390 px,
 * light and dark, on the --slice 2 demo world. Opt-in, after a full run (it only reads):
 * `LK_E2E_EVIDENCE=cp3 npm run test:e2e -- --no-build e2e/evidence-cp3.spec.ts --project=desktop`.
 */

const OUT = path.resolve(__dirname, "../../../docs/evidence/checkpoint-3");
const WIDTHS = [
  { name: "1440", width: 1440, height: 900 },
  { name: "390", width: 390, height: 844 },
] as const;
const THEMES = ["light", "dark"] as const;

test.skip(process.env.LK_E2E_EVIDENCE !== "cp3", "checkpoint-3 evidence runs only with LK_E2E_EVIDENCE=cp3");
test.describe.configure({ mode: "serial" });

let world: World;

test.beforeAll(async ({ request }) => {
  onlyOnProjects("desktop");
  world = await loadWorld(request);
  mkdirSync(OUT, { recursive: true });
});

type Shot = { name: string; person: PersonKey; url: (w: World) => string | null };

const SHOTS: readonly Shot[] = [
  { name: "products-list", person: "PRIYA", url: () => "/products" },
  { name: "product-record", person: "PRIYA", url: (w) => (ref(w, "OAK_TRAY") ? `/products/${ref(w, "OAK_TRAY")}` : null) },
  { name: "product-media", person: "PRIYA", url: (w) => (ref(w, "OAK_TRAY") ? `/products/${ref(w, "OAK_TRAY")}?tab=media` : null) },
  { name: "taxonomy", person: "PRIYA", url: () => "/products/taxonomy" },
  { name: "price-list", person: "PRIYA", url: (w) => (ref(w, "PL_EXP_EUR") ? `/products/price-lists/${ref(w, "PL_EXP_EUR")}` : null) },
  { name: "imports", person: "PRIYA", url: () => "/settings/imports/new" },
  { name: "users", person: "PRIYA", url: () => "/settings/users" },
  { name: "roles", person: "PRIYA", url: () => "/settings/roles" },
  { name: "security", person: "MEERA", url: () => "/settings/security" },
  { name: "custom-products", person: "MEERA", url: () => "/sales/custom-products" },
  { name: "samples", person: "MEERA", url: () => "/sales/samples" },
  { name: "operations", person: "RAVI", url: () => "/operations" },
  { name: "cut-plan", person: "RAVI", url: (w) => (ref(w, "CUT_PLAN_WALNUT") ? `/operations/cutting/${ref(w, "CUT_PLAN_WALNUT")}` : null) },
  { name: "challans", person: "RAVI", url: () => "/operations/challans" },
  { name: "challan", person: "RAVI", url: (w) => (ref(w, "DC-2026-0001") ? `/operations/challans/${ref(w, "DC-2026-0001")}` : null) },
  { name: "search", person: "SAHIL", url: () => "/search?q=oak" },
];

async function open(page: Page, person: PersonKey, theme: (typeof THEMES)[number], width: (typeof WIDTHS)[number], url: string) {
  await signInAs(page, person);
  await page.context().addCookies([{ name: "lk_ui", value: `theme=${theme}&motion=reduced`, url: test.info().project.use.baseURL! }]);
  await page.setViewportSize({ width: width.width, height: width.height });
  await page.goto(url);
  await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
  await expect(page.getByRole("main")).toBeVisible();
  await page.waitForLoadState("networkidle");
}

for (const theme of THEMES) {
  for (const width of WIDTHS) {
    test(`checkpoint-3 evidence ${width.name} ${theme}`, async ({ page }) => {
      test.setTimeout(240_000);
      for (const shot of SHOTS) {
        const url = shot.url(world);
        if (!url) continue;
        await open(page, shot.person, theme, width, url);
        await page.screenshot({ path: path.join(OUT, `${shot.name}-${width.name}-${theme}.png`), fullPage: false });
      }
    });
  }
}
