import { mkdirSync } from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { signInAs, onlyOnProjects, type PersonKey } from "./support/world";

/**
 * Checkpoint-4a evidence (docs/evidence/checkpoint-4a/): the screens the Slice-3 stage-1 lanes added (agents runtime,
 * WhatsApp) at 1440 and 390 px, light and dark, on the --slice 2 demo world. Opt-in, after a full run:
 * `LK_E2E_EVIDENCE=cp4a npm run test:e2e -- --no-build e2e/evidence-cp4a.spec.ts --project=desktop`.
 * The trace is of a run the spec starts itself (Meera's scenario-C request, streamed over SSE); `/r/[token]` is shown
 * with an invalid token, because a valid link resolves once and redirects at once.
 */

const OUT = path.resolve(__dirname, "../../../docs/evidence/checkpoint-4a");
const WIDTHS = [
  { name: "1440", width: 1440, height: 900 },
  { name: "390", width: 390, height: 844 },
] as const;
const THEMES = ["light", "dark"] as const;

test.skip(process.env.LK_E2E_EVIDENCE !== "cp4a", "checkpoint-4a evidence runs only with LK_E2E_EVIDENCE=cp4a");
test.describe.configure({ mode: "serial" });

let correlationId = "";

test.beforeAll(() => {
  onlyOnProjects("desktop");
  mkdirSync(OUT, { recursive: true });
});

test("a run to trace", async ({ page }) => {
  await signInAs(page, "MEERA");
  let runId = "";
  page.on("request", (request) => {
    const match = /\/api\/v1\/agents\/runs\/([0-9a-f-]{36})\/events/.exec(request.url());
    if (match) runId = match[1];
  });
  await page.goto("/today");
  await page.getByRole("textbox", { name: /Ask about your day/ }).fill("Prepare Nordhaus's usual oak tray quote");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.locator('[data-card="quote_draft"]')).toBeVisible({ timeout: 30_000 });
  expect(runId).not.toBe("");
  const run = await page.request.get(`/api/v1/agents/runs/${runId}`);
  expect(run.status()).toBe(200);
  const body = (await run.json()) as { run?: { correlation_id?: string } };
  correlationId = body.run?.correlation_id ?? "";
  expect(correlationId).not.toBe("");
});

type Shot = { name: string; person: PersonKey; url: () => string | null };

const SHOTS: readonly Shot[] = [
  { name: "settings-ai", person: "PRIYA", url: () => "/settings/ai" },
  { name: "trace", person: "MEERA", url: () => (correlationId ? `/settings/ai/traces/${correlationId}` : null) },
  { name: "settings-whatsapp", person: "MEERA", url: () => "/settings/whatsapp" },
  { name: "settings-whatsapp-admin", person: "PRIYA", url: () => "/settings/whatsapp" },
  { name: "review-link-invalid", person: "MEERA", url: () => "/r/not-a-valid-token" },
  { name: "settings-hub", person: "PRIYA", url: () => "/settings" },
];

async function open(page: Page, person: PersonKey, theme: (typeof THEMES)[number], width: (typeof WIDTHS)[number], url: string) {
  await signInAs(page, person);
  await page.context().addCookies([{ name: "lk_ui", value: `theme=${theme}&motion=reduced`, url: test.info().project.use.baseURL! }]);
  await page.setViewportSize({ width: width.width, height: width.height });
  await page.goto(url);
  await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
  await expect(page.getByRole("main")).toBeVisible();
  // the WhatsApp simulator polls every 2 s, so the network never idles there; give it a moment instead
  await page.waitForLoadState("load");
  await page.waitForTimeout(1_500);
}

for (const theme of THEMES) {
  for (const width of WIDTHS) {
    test(`checkpoint-4a evidence ${width.name} ${theme}`, async ({ page }) => {
      test.setTimeout(180_000);
      for (const shot of SHOTS) {
        const url = shot.url();
        if (!url) continue;
        await open(page, shot.person, theme, width, url);
        await page.screenshot({ path: path.join(OUT, `${shot.name}-${width.name}-${theme}.png`), fullPage: false });
      }
    });
  }
}
