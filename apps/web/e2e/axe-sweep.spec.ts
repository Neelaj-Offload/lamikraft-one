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
