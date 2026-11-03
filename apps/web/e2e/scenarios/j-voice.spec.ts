import { expect, test, type Page } from "@playwright/test";
import { expected, loadWorld, moneyText, onlyOnProjects, signInAs, type World } from "../support/world";

/**
 * Scenario J (PLAN.md Slice 3, PARITY SCN-J1/J3) and scenario C via voice, in Chromium with the
 * fake media device from playwright.config.ts: push-to-talk records, the Demo STT returns its
 * labelled scripted phrase for the fake tone, the edited transcript is sent once and drafts the
 * quote with a read-back; a denied microphone keeps the text path usable; Stop/push-to-talk
 * interrupts a spoken reply; offline, a transcript becomes "Queued draft — not sent" and is sent
 * on reconnect with the same utterance id (one turn). Written by the voice-vision lane.
 */

const UTTERANCE = "Prepare Nordhaus's usual oak tray quote";

// spoken replies play without a user gesture in the test browser
test.use({
  launchOptions: {
    args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", "--autoplay-policy=no-user-gesture-required"],
  },
});

let world: World;

test.beforeAll(async ({ request }) => {
  onlyOnProjects("desktop", "phone");
  world = await loadWorld(request);
});

const voice = (page: Page) => page.getByRole("group", { name: "Voice and screen" });
const talk = (page: Page) => voice(page).getByRole("button", { name: /^(Hold to talk|Stop recording)$/ });

async function recordOnce(page: Page): Promise<void> {
  await expect(talk(page)).toBeEnabled({ timeout: 10_000 });
  await talk(page).click(); // a short press toggles recording on
  await expect(voice(page).getByRole("status").filter({ hasText: "Recording" })).toBeVisible();
  await page.waitForTimeout(700);
  await talk(page).click(); // and the second press stops it
  await expect(page.getByRole("textbox", { name: /What you said|Correction/ })).toBeVisible({ timeout: 15_000 });
}

test("fake_media_voice_turn_sends_once_and_reads_back", async ({ page }) => {
  await signInAs(page, "MEERA");
  await page.goto("/today");
  await recordOnce(page);
  await expect(voice(page).getByText("Demo transcript — not from your recording")).toBeVisible();
  const transcript = page.getByRole("textbox", { name: /What you said/ });
  await transcript.fill(UTTERANCE);
  const send = page.getByRole("group", { name: "Voice and screen" }).getByRole("button", { name: "Send", exact: true });
  await send.click();

  const card = page.locator('[data-card="quote_draft"]');
  await expect(card).toBeVisible({ timeout: 20_000 });
  await expect(card).toContainText(moneyText(expected(world, "SCENARIO_C_TOTAL"), "EUR"));
  await expect(page.getByRole("region", { name: "Read-back" })).toContainText("Total EUR 5,760.00.");
  await expect(page.getByRole("region", { name: "Read-back" })).toContainText(/draft, not sent/);
  // one exchange: the transcript was sent once and the editor is gone
  await expect(page.getByRole("region", { name: "Conversation with the assistant" }).getByText(UTTERANCE, { exact: true })).toHaveCount(1);
  await expect(page.getByRole("textbox", { name: /What you said/ })).toHaveCount(0);
});

test("mic_denied_keeps_the_text_path", async ({ page }) => {
  await page.addInitScript(() => {
    navigator.mediaDevices.getUserMedia = () => Promise.reject(new DOMException("blocked", "NotAllowedError"));
  });
  await signInAs(page, "MEERA");
  await page.goto("/today");
  await expect(talk(page)).toBeEnabled({ timeout: 10_000 });
  await talk(page).click();
  await expect(voice(page).getByRole("alert").filter({ hasText: "The microphone is blocked" })).toBeVisible();
  const text = page.getByRole("textbox", { name: /Ask about your day/ });
  await expect(text).toBeFocused();
  await expect(talk(page)).toBeDisabled(); // voice stays off until the person retries
  await expect(voice(page).getByRole("button", { name: "Try the microphone again" })).toBeVisible();
  await text.fill(UTTERANCE);
  await page.getByRole("button", { name: "Send", exact: true }).first().click();
  await expect(page.locator('[data-card="quote_draft"]')).toBeVisible({ timeout: 20_000 });
});

test("interrupt_stops_speech", async ({ page }) => {
  await signInAs(page, "MEERA");
  await page.goto("/today");
  const speak = page.getByRole("switch", { name: "Speak replies" });
  await expect(speak).toBeVisible({ timeout: 10_000 });
  await voice(page).getByText("Speak replies").click(); // the switch's input is visually hidden
  await expect(speak).toBeChecked();
  await recordOnce(page);
  await page.getByRole("textbox", { name: /What you said/ }).fill(UTTERANCE);
  await page.getByRole("group", { name: "Voice and screen" }).getByRole("button", { name: "Send", exact: true }).click();
  await expect(page.locator('[data-card="quote_draft"]')).toBeVisible({ timeout: 20_000 });
  const stop = page.getByRole("button", { name: "Stop speaking" });
  await expect(stop).toBeVisible({ timeout: 10_000 });
  await stop.click();
  await expect(stop).toHaveCount(0);
  await expect(voice(page).getByRole("status").filter({ hasText: "Speaking" })).toHaveCount(0);
});

test("offline_transcript_is_a_queued_draft_never_a_commit", async ({ page, context }) => {
  await signInAs(page, "MEERA");
  await page.goto("/today");
  await recordOnce(page);
  await page.getByRole("textbox", { name: /What you said/ }).fill(UTTERANCE);
  await context.setOffline(true);
  await page.getByRole("group", { name: "Voice and screen" }).getByRole("button", { name: "Send", exact: true }).click();
  const queue = page.getByRole("region", { name: "Queued drafts" });
  await expect(queue).toContainText("Queued draft — not sent");
  await expect(page.locator('[data-card="quote_draft"]')).toHaveCount(0);
  await expect(page.locator('[data-card="receipt"]')).toHaveCount(0);
  await context.setOffline(false);
  await expect(queue).toContainText("You're back online");
  await queue.getByRole("button", { name: "Send draft" }).click();
  await expect(page.locator('[data-card="quote_draft"]')).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole("region", { name: "Queued drafts" })).toHaveCount(0);
});
