import { mkdirSync } from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { fact, loadWorld, onlyOnProjects, ref, signInAs, type PersonKey, type World } from "./support/world";

/**
 * Slice-1 evidence screenshots (docs/evidence/slice-1/): Today, Inbox, the quote list, the quote
 * workspace, the review page and an assistant card, at 1440 and 390 px wide, light and dark.
 * Not part of the default run (it drafts quotes through the assistant, which would move the next
 * quote number under scenario C): `LK_E2E_EVIDENCE=1 npm run test:e2e -- --no-build e2e/evidence.spec.ts`
 * after a scenario run, on the desktop project.
 */

const OUT = path.resolve(__dirname, "../../../docs/evidence/slice-1");
const WIDTHS = [
  { name: "1440", width: 1440, height: 900 },
  { name: "390", width: 390, height: 844 },
] as const;
const THEMES = ["light", "dark"] as const;

// only its own value: the later checkpoint specs use LK_E2E_EVIDENCE=cp3/cp4a/cp4/cp5, which must not rewrite these
test.skip(process.env.LK_E2E_EVIDENCE !== "1", "evidence screenshots run only with LK_E2E_EVIDENCE=1");
test.describe.configure({ mode: "serial" });

let world: World;

test.beforeAll(async ({ request }) => {
  onlyOnProjects("desktop");
  world = await loadWorld(request);
  mkdirSync(OUT, { recursive: true });
});

async function open(page: Page, person: PersonKey, theme: (typeof THEMES)[number], width: (typeof WIDTHS)[number], url: string) {
  await signInAs(page, person);
  await page.context().addCookies([{ name: "lk_ui", value: `theme=${theme}&motion=reduced`, url: test.info().project.use.baseURL! }]);
  await page.setViewportSize({ width: width.width, height: width.height });
  await page.goto(url);
  await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
  await expect(page.getByRole("main")).toBeVisible();
  await page.waitForLoadState("networkidle");
}

async function shoot(page: Page, name: string, theme: string, width: string) {
  await page.screenshot({ path: path.join(OUT, `${name}-${width}-${theme}.png`), fullPage: false });
}

for (const theme of THEMES) {
  for (const width of WIDTHS) {
    test(`evidence ${width.name} ${theme}`, async ({ page }) => {
      test.setTimeout(120_000);
      const quoteId = ref(world, fact(world, "quotes", "MAISON_OVERRIDE") ?? "");
      const proposalId = ref(world, "PROP_MAISON");
      expect(quoteId, "Maison quote id").not.toBeNull();
      expect(proposalId, "Maison review id").not.toBeNull();

      await open(page, "MEERA", theme, width, "/today");
      await shoot(page, "today", theme, width.name);

      await open(page, "MEERA", theme, width, "/inbox");
      await shoot(page, "inbox", theme, width.name);

      await open(page, "MEERA", theme, width, "/sales/quotes");
      await shoot(page, "quote-list", theme, width.name);

      await open(page, "MEERA", theme, width, `/sales/quotes/${quoteId}`);
      await shoot(page, "quote-workspace", theme, width.name);

      await open(page, "SAHIL", theme, width, `/inbox/approvals/${proposalId}`);
      await shoot(page, "review-page", theme, width.name);

      await open(page, "MEERA", theme, width, "/today");
      await page.getByRole("textbox", { name: /Ask about your day/ }).fill("Prepare Nordhaus's usual oak tray quote");
      await page.getByRole("button", { name: "Send", exact: true }).click();
      const card = page.locator('[data-card="quote_draft"]');
      await expect(card).toBeVisible({ timeout: 30_000 });
      await card.scrollIntoViewIfNeeded();
      await shoot(page, "assistant-card", theme, width.name);
    });
  }
}
