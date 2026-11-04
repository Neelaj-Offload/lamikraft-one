import { expect, test, type Page } from "@playwright/test";
import { loadWorld, onlyOnProjects, ref, signInAs, type World } from "../support/world";

/**
 * Scenario B (motion-system §8): during an active voice pin ("Listen to my day"), a source change that writes a
 * new briefing version never moves the rows on screen and never shows the "N updates" pill; the list changes only
 * after the person stops listening. Also: the Listen controls are keyboard operable (Escape stops) and the
 * waveform is a static meter under reduced motion. A new customer message for Meera is the source change; the
 * worker refreshes her briefing. Desktop only: the change is a real write to the shared e2e world.
 */

test.describe.configure({ mode: "serial", timeout: 120_000 });

let world: World;

test.beforeAll(async ({ request }) => {
  onlyOnProjects("desktop");
  world = await loadWorld(request);
});

function titles(page: Page): Promise<string[]> {
  return page.locator('article[data-reveal="item"] h3').allTextContents();
}

/** The latest version of Meera's briefing on the server (the UI poll reports it even while a pin holds the view). */
async function latestVersion(page: Page): Promise<number> {
  const response = await page.request.get("/api/v1/ui/poll");
  const body = (await response.json()) as Record<string, unknown>;
  const sections = (body.sections as Record<string, unknown> | undefined) ?? body;
  const briefing = sections.briefing as { version?: number; value?: { version?: number } } | undefined;
  return Number(briefing?.version ?? briefing?.value?.version ?? 0);
}

async function origin(page: Page): Promise<string> {
  return new URL(test.info().project.use.baseURL ?? page.url()).origin;
}

test("B: an active voice pin keeps the list in place while a new version arrives", async ({ page, request }) => {
  await signInAs(page, "MEERA");
  await page.goto("/today");
  await expect(page.locator('article[data-reveal="item"]').first()).toBeVisible();
  const before = await titles(page);
  expect(before.length).toBeGreaterThan(0);

  await page.getByRole("button", { name: "Listen to my day" }).click();
  const panel = page.getByTestId("listen-panel");
  await expect(panel).toHaveAttribute("data-phase", "speaking", { timeout: 15_000 });
  await expect(panel).toContainText("Demo voice");
  await expect(page.getByText("Listening: the list stays in this order until you stop.")).toBeVisible();
  await page.getByRole("button", { name: "Pause" }).click();
  await expect(panel).toHaveAttribute("data-phase", "paused");

  const start = await latestVersion(page);
  const maison = ref(world, "MAISON");
  const meera = ref(world, "MEERA");
  expect(maison, "MAISON party ref").not.toBeNull();
  // the source change comes from a separate API session (the page's CSRF token rotates at bootstrap): sign in, then
  // send the app's Origin and the double-submit token from that session's lk_csrf cookie
  const headers = { Origin: await origin(page) };
  expect((await request.post("/api/v1/_test/sign-in", { data: { user_key: "MEERA" }, headers })).status()).toBe(200);
  const csrf = (await request.storageState()).cookies.find((cookie) => cookie.name === "lk_csrf")?.value ?? "";
  const created = await request.post("/api/v1/sales/customer-messages", {
    headers: { ...headers, "X-CSRF-Token": csrf, "Idempotency-Key": `b-stability-${Date.now()}` },
    data: { party_id: maison, channel: "email", subject: "Scenario B", body: "Could you confirm the delivery date?", assignee_user_id: meera },
  });
  expect(created.status(), await created.text()).toBe(201);
  await expect.poll(() => latestVersion(page), { timeout: 45_000, intervals: [1_000] }).toBeGreaterThan(start);

  // the page refetches on focus and on the UI poll: the pinned version is served, nothing moves
  const refetched = page.waitForResponse((r) => r.url().includes("/api/v1/briefings/today") && r.status() === 200);
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));
  await refetched.catch(() => undefined);
  expect(await titles(page)).toEqual(before);
  await expect(page.getByText(/^\d+ updates?$/)).toHaveCount(0);

  // keyboard: Resume, then Escape stops listening; the newer version is applied afterwards
  await page.getByRole("button", { name: "Resume" }).focus();
  await page.keyboard.press("Enter");
  await expect(panel).toHaveAttribute("data-phase", "speaking");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: "Listen to my day" })).toBeVisible();
  await expect.poll(() => titles(page), { timeout: 20_000 }).not.toEqual(before);
});

test("B: the waveform is a static meter under reduced motion", async ({ browser }) => {
  const context = await browser.newContext({ reducedMotion: "reduce", baseURL: test.info().project.use.baseURL });
  const page = await context.newPage();
  try {
    await signInAs(page, "MEERA");
    await page.goto("/today");
    await page.getByRole("button", { name: "Listen to my day" }).click();
    await expect(page.getByTestId("listen-panel")).toHaveAttribute("data-phase", "speaking", { timeout: 15_000 });
    await expect(page.getByTestId("listen-waveform")).toHaveAttribute("data-state", "static");
    await page.getByRole("button", { name: "Stop" }).click();
    await expect(page.getByRole("button", { name: "Listen to my day" })).toBeVisible();
  } finally {
    await context.close();
  }
});
