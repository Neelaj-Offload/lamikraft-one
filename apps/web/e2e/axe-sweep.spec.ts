import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { routes, type RouteDefinition } from "../src/lib/routes";
import { fact, loadWorld, onlyOnProjects, ref, signInAs, type World } from "./support/world";

/**
 * Accessibility sweep: every route in the manifest, in the light and the dark theme, with
 * WCAG 2.2 AA rules (@axe-core/playwright is installed). Dynamic segments are filled from the
 * fixture world; a route whose record the world does not publish is skipped with a note.
 * Session routes run as Sahil (management scope sees every Slice-1 area); public routes run
 * signed out. Desktop project only; the phone layout is covered by scenario C.
 */

const WCAG_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

/** Fixture keys that can fill each dynamic segment, in order of preference. */
function paramCandidates(world: World): Record<string, () => string | null> {
  // Business keys come from the published facts (`keys.QUOTES`, `keys.ENQUIRIES`); their ids from `refs`.
  const byFact = (name: string, key: string) => {
    const businessKey = fact(world, name, key);
    return businessKey ? ref(world, businessKey) : null;
  };
  return {
    quoteId: () => byFact("quotes", "NORDHAUS_DRAFT") ?? byFact("quotes", "MAISON_OVERRIDE"),
    proposalId: () => ref(world, "PROP_MAISON") ?? ref(world, "PROP_NORDHAUS"),
    enquiryId: () => byFact("enquiries", "MAISON"),
    // Checkpoint 2 routes: ids by fixture key (seed/world/{catalogue,parties,pricing}.py refs).
    productId: () => ref(world, "OAK_TRAY"),
    partyId: () => ref(world, "MAISON") ?? ref(world, "NORDHAUS"),
    priceListId: () => ref(world, "PL_EXP_EUR"),
    // Slice-2 challans (seed/world/challans.py; published by business key and fixture key when seeded with --slice 2).
    challanId: () => ref(world, "DC-2026-0001") ?? ref(world, "DC_JOB_WORK"),
    // Slice-2 merge: the seeded walnut cut plan (keys.CUT_PLAN_REFS.WALNUT; e2e seeds at --slice 2)
    planId: () => ref(world, "CUT_PLAN_WALNUT"),
    // Slice-3 stage-1 merge: a review link resolves once and redirects, so the sweep checks the invalid-link state
    token: () => "not-a-valid-token",
    // Slice-4 merge (e2e seeds at --slice 4): the opening batch, PO-2026-0001, WO-2026-0001 and its BOM, routing and
    // work centre. Orders, requisitions, receipts, inspections, shipments, packing lists, pick lists, counts,
    // adjustments and transfers are not fixture records; their screens are covered by the scenario specs.
    batchId: () => ref(world, "OB_MAIN"),
    poId: () => byFact("purchase_orders", "KAVERI_WALNUT") ?? ref(world, "PO_KAVERI"),
    workOrderId: () => byFact("work_orders", "PANEL_SETS") ?? ref(world, "WO_PANEL_SETS"),
    bomId: () => ref(world, "BOM_PANEL_SET"),
    routingId: () => ref(world, "ROUTING_PANEL_SET"),
    workCenterId: () => ref(world, "WC_PANEL_SAW"),
    // Slice-5 merge (e2e seeds at --slice 5): the Maison receipt (keys.FINANCE_REFS). Invoices, credit notes, samples
    // and migration runs are not fixture records (`m-finance`, `o-offcut-lineage-what-if` and `m-migration` cover
    // them); the what-if screen and the finance lists need no record.
    receiptId: () => ref(world, "RCPT_MAISON"),
  };
}

function concretePath(route: RouteDefinition, world: World): string | null {
  const candidates = paramCandidates(world);
  let missing = false;
  const path = route.path.replace(/\[([^\]]+)\]/g, (_, name: string) => {
    const value = candidates[name]?.() ?? null;
    if (!value) missing = true;
    return value ?? "";
  });
  return missing ? null : path;
}

for (const theme of ["light", "dark"] as const) {
  for (const route of routes as readonly RouteDefinition[]) {
    test(`${route.path} has no WCAG 2.2 AA violations (${theme})`, async ({ page, context, baseURL, request }) => {
      onlyOnProjects("desktop");
      const world = await loadWorld(request);
      const path = concretePath(route, world);
      test.skip(path === null, `no fixture record for ${route.path}`);

      if (route.access === "session") await signInAs(page, "SAHIL");
      else await context.clearCookies();
      await context.addCookies([{ name: "lk_ui", value: `theme=${theme}&motion=reduced`, url: baseURL! }]);

      const response = await page.goto(path!);
      expect(response?.status(), `GET ${path}`).toBeLessThan(500);
      await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
      await expect(page.getByRole("main")).toBeVisible();
      // Let client queries settle so the sweep sees the loaded screen, not its skeleton.
      await page.waitForLoadState("networkidle");

      const results = await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze();
      expect(results.violations, `${route.id} (${theme})`).toEqual([]);
    });
  }
}
