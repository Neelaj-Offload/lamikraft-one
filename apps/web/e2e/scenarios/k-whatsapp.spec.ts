import { expect, test, type Locator, type Page } from "@playwright/test";
import { expected, loadWorld, moneyText, onlyOnProjects, signInAs, type World } from "../support/world";

/**
 * Scenarios C and K through the WhatsApp Demo simulator (Settings › WhatsApp). Every simulator message goes through
 * the signed webhook route, the inbox and the worker, exactly as a Meta delivery would (ADR-030). Meera links her
 * demo number with a one-time code, asks for Nordhaus's usual oak tray quote by WhatsApp text and by demo voice note,
 * opens the "Review quote" link (a single-use, 15-minute `/r/<token>` link bound to her) which redirects to the quote
 * workspace, sees a used button refused, and opts out of proactive messages with STOP. Desktop only: the demo number
 * is per user, so a second project would relink the same identity mid-run. Added at the Slice-3 stage-1 merge.
 */

const UTTERANCE = "Prepare Nordhaus's usual oak tray quote";

test.describe.configure({ mode: "serial" });

let world: World;

test.beforeAll(async ({ request }) => {
  onlyOnProjects("desktop");
  world = await loadWorld(request);
});

function thread(page: Page): Locator {
  // the conversation log (aria-live) inside the Simulator card
  return page.locator('div[aria-live="polite"][aria-label="Simulator"]');
}

async function say(page: Page, text: string) {
  await page.getByRole("textbox", { name: "Message" }).fill(text);
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "Message" })).toHaveValue("");
}

/** The last assistant bubble whose text contains `text` (the simulator polls every 2 s; the worker answers). */
function reply(page: Page, text: string | RegExp): Locator {
  return thread(page).locator("li").filter({ hasText: text }).last();
}

async function openWhatsApp(page: Page) {
  await signInAs(page, "MEERA");
  await page.goto("/settings/whatsapp");
  await expect(page.getByRole("heading", { level: 1, name: "WhatsApp" })).toBeVisible();
  await expect(page.getByText("Demo — not connected").first()).toBeVisible();
}

test("C/K: Meera links her demo number through the signed webhook", async ({ page }) => {
  await openWhatsApp(page);
  await page.getByRole("button", { name: /Create (link code|a new code)/ }).click();
  const shown = (await page.getByTestId("enrolment-code").textContent()) ?? "";
  const code = shown.replace(/\s+/g, "");
  expect(code).toMatch(/^\d{8}$/);

  await say(page, `LINK ${code}`);
  // the code is masked in the stored thread; the worker answers with the link confirmation
  await expect(reply(page, "LINK ••••••••")).toBeVisible({ timeout: 20_000 });
  await expect(reply(page, /Demo: Linked to Lamikraft One as Meera/)).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole("table").getByText("Linked", { exact: true }).first()).toBeVisible({ timeout: 10_000 });
});

test("C: a WhatsApp text drafts the quote; Review quote opens a bound link that lands on the workspace", async ({ page }) => {
  const total = expected(world, "SCENARIO_C_TOTAL");
  await openWhatsApp(page);
  await say(page, UTTERANCE);

  const draft = reply(page, /Demo: Draft ready \([A-Z]{2,4}-QT-\d{4}-\d{4}\)/);
  await expect(draft).toBeVisible({ timeout: 30_000 });
  await expect(draft).toContainText(`Total ${moneyText(total, "EUR")}`);
  await expect(draft).toContainText("Status: draft, not sent.");
  const number = /[A-Z]{2,4}-QT-\d{4}-\d{4}/.exec((await draft.textContent()) ?? "")?.[0] ?? "";
  expect(number).not.toBe("");

  await draft.getByRole("button", { name: "Review quote" }).click();
  const link = reply(page, "/r/");
  await expect(link).toBeVisible({ timeout: 20_000 });
  await expect(link).toContainText("15 minutes");
  const token = /\/r\/([A-Za-z0-9_-]+)/.exec((await link.textContent()) ?? "")?.[1] ?? "";
  expect(token).not.toBe("");

  // K: the same button cannot be used twice
  await draft.getByRole("button", { name: "Review quote" }).click();
  await expect(reply(page, "Demo: That button was already used.")).toBeVisible({ timeout: 20_000 });

  // the review link resolves once, for Meera only, and redirects to the canonical quote screen
  await page.goto(`/r/${token}`);
  await expect(page).toHaveURL(/\/sales\/quotes\/[0-9a-f-]{36}$/, { timeout: 15_000 });
  await expect(page.getByRole("heading", { level: 1, name: number })).toBeVisible();
});

test("C: a demo voice note is echoed as a transcript and drafts the same quote", async ({ page }) => {
  await openWhatsApp(page);
  await page.getByRole("button", { name: /Demo voice note/ }).click();
  await page.getByRole("option", { name: /Prepare Nordhaus's usual oak tray quote/ }).click();
  await page.getByRole("button", { name: "Send voice note" }).click();
  await expect(reply(page, /Demo: I heard \(Demo transcript\)/)).toBeVisible({ timeout: 30_000 });
  await expect(reply(page, /Demo: Draft ready/)).toBeVisible({ timeout: 30_000 });
});

test("K: STOP turns proactive messages off with a confirmation", async ({ page }) => {
  await openWhatsApp(page);
  await say(page, "STOP");
  await expect(reply(page, /Proactive messages are off/)).toBeVisible({ timeout: 20_000 });
  await say(page, "START");
  await expect(reply(page, /Proactive messages are on again/)).toBeVisible({ timeout: 20_000 });
});
