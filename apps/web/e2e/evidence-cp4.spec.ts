import { mkdirSync } from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { signInAs, onlyOnProjects, type PersonKey } from "./support/world";

/**
 * Checkpoint-4 evidence (docs/evidence/checkpoint-4/): the screens the Slice-3 stage-2 lanes added (voice and
 * vision in the composer, Listen to my day, the delta, all-items and item pages) at 1440 and 390 px, light and
 * dark, on the --slice 2 demo world. Opt-in, after a full run:
 * `LK_E2E_EVIDENCE=cp4 npm run test:e2e -- --no-build e2e/evidence-cp4.spec.ts --project=desktop`.
 */

const OUT = path.resolve(__dirname, "../../../docs/evidence/checkpoint-4");
const WIDTHS = [
  { name: "1440", width: 1440, height: 900 },
  { name: "390", width: 390, height: 844 },
] as const;
const THEMES = ["light", "dark"] as const;

test.skip(process.env.LK_E2E_EVIDENCE !== "cp4", "checkpoint-4 evidence runs only with LK_E2E_EVIDENCE=cp4");
test.describe.configure({ mode: "serial" });

let itemId = "";

test.beforeAll(() => {
  onlyOnProjects("desktop");
  mkdirSync(OUT, { recursive: true });
});

test("an item to show", async ({ page }) => {
  await signInAs(page, "MEERA");
  const today = await page.request.get("/api/v1/briefings/today");
  expect(today.status()).toBe(200);
  const body = (await today.json()) as { sections?: Array<{ issue_ids?: string[] }> };
  itemId = body.sections?.flatMap((s) => s.issue_ids ?? [])[0] ?? "";
  expect(itemId).not.toBe("");
});

type Shot = { name: string; person: PersonKey; url: () => string | null; then?: (page: Page) => Promise<void> };

const SHOTS: readonly Shot[] = [
  { name: "today", person: "MEERA", url: () => "/today" },
  {
    name: "today-listen-paused",
    person: "MEERA",
    url: () => "/today",
    then: async (page) => {
      await page.getByRole("button", { name: "Listen to my day" }).click();
      const panel = page.getByTestId("listen-panel");
      await expect(panel).toHaveAttribute("data-phase", "speaking", { timeout: 15_000 });
      await panel.getByRole("button", { name: "Pause" }).click();
      await expect(panel).toHaveAttribute("data-phase", "paused");
    },
  },
  { name: "today-changes", person: "MEERA", url: () => "/today/changes" },
  { name: "today-all", person: "MEERA", url: () => "/today/all" },
  { name: "today-item", person: "MEERA", url: () => (itemId ? `/today/items/${itemId}` : null) },
  {
    name: "composer-voice",
    person: "MEERA",
    url: () => "/today",
    then: async (page) => {
      const group = page.getByRole("group", { name: "Voice and screen" });
      await expect(group).toBeVisible();
      await group.scrollIntoViewIfNeeded();
    },
  },
];

async function open(page: Page, person: PersonKey, theme: (typeof THEMES)[number], width: (typeof WIDTHS)[number], url: string) {
  await signInAs(page, person);
  await page.context().addCookies([{ name: "lk_ui", value: `theme=${theme}&motion=reduced`, url: test.info().project.use.baseURL! }]);
  await page.setViewportSize({ width: width.width, height: width.height });
  await page.goto(url);
  await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
  await expect(page.getByRole("main")).toBeVisible();
  await page.waitForLoadState("load");
  await page.waitForTimeout(1_000);
}

for (const theme of THEMES) {
  for (const width of WIDTHS) {
    test(`checkpoint-4 evidence ${width.name} ${theme}`, async ({ page }) => {
      test.setTimeout(240_000);
      for (const shot of SHOTS) {
        const url = shot.url();
        if (!url) continue;
        await open(page, shot.person, theme, width, url);
        if (shot.then) await shot.then(page);
        await page.screenshot({ path: path.join(OUT, `${shot.name}-${width.name}-${theme}.png`), fullPage: false });
        if (shot.name === "today-listen-paused") {
          await page.getByTestId("listen-panel").getByRole("button", { name: "Stop" }).click();
        }
      }
    });
  }
}
