import { expect, test, type Page } from "@playwright/test";
import { expected, loadWorld, moneyText, onlyOnProjects, signInAs, type World } from "./support/world";

/**
 * Scenario C (PLAN.md Slice 1 exit): Meera asks the assistant for Nordhaus's usual oak tray
 * quote, opens the draft, checks the figures and requests review; Sahil approves it from the
 * Inbox; Meera marks it sent and the issued revision's PDF downloads as application/pdf.
 * Runs at the desktop and phone viewports (the tablet project skips it). Written by the web
 * lane; run by the integrator (`npm run test:e2e`).
 */

const UTTERANCE = "Prepare Nordhaus's usual oak tray quote";

test.describe.configure({ mode: "serial" });

let world: World;
let quotePath = "";
let quoteNumber = "";

test.beforeAll(async ({ request }) => {
  onlyOnProjects("desktop", "phone");
  world = await loadWorld(request);
});

async function composer(page: Page) {
  return page.getByRole("textbox", { name: /Ask about your day|Ask about this quote/ });
}

test("Meera drafts the quote through the assistant and requests review", async ({ page }) => {
  const total = expected(world, "SCENARIO_C_TOTAL");
  const quantity = expected(world, "SCENARIO_C_QTY");
  await signInAs(page, "MEERA");
  await page.goto("/today");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();

  await (await composer(page)).fill(UTTERANCE);
  await page.getByRole("button", { name: "Send" }).click();

  const card = page.locator('[data-card="quote_draft"]');
  await expect(card).toBeVisible({ timeout: 20_000 });
  // The first run on a fresh world allocates SCENARIO_C_NEW; a second project on the same
  // database gets the next number, so only the desktop run asserts the exact number.
  const heading = (await card.getByRole("heading").first().textContent()) ?? "";
  const number = /[A-Z]{2,4}-QT-\d{4}-\d{4}/.exec(heading)?.[0] ?? "";
  if (test.info().project.name === "desktop") expect(number).toBe(expected(world, "SCENARIO_C_NEW"));
  quoteNumber = number;
  await expect(card).toContainText(moneyText(total, "EUR"));
  await expect(card).toContainText(`${quantity} pcs`);

  await card.getByRole("link", { name: "Open the draft" }).click();
  await expect(page).toHaveURL(/\/sales\/quotes\/[0-9a-f-]{36}$/);
  quotePath = new URL(page.url()).pathname;

  await expect(page.getByRole("heading", { level: 1, name: number })).toBeVisible();
  await expect(page.getByRole("textbox", { name: /^Quantity/ }).first()).toHaveValue(quantity);
  await expect(page.locator('[data-totals="saved"]')).toContainText(moneyText(total, "EUR"));

  await page.getByTestId("quote-commands").getByRole("button", { name: "Request review" }).click();
  await expect(page.getByText("Review requested", { exact: false }).first()).toBeVisible();
});

test("Sahil approves it from the Inbox", async ({ page }) => {
  const number = quoteNumber;
  expect(number, "the draft from the first step").not.toBe("");
  await signInAs(page, "SAHIL");
  await page.goto("/inbox/approvals");
  await page.getByRole("link", { name: new RegExp(number) }).first().click();
  await expect(page).toHaveURL(/\/inbox\/approvals\/[0-9a-f-]{36}$/);
  await expect(page.getByRole("heading", { level: 1 })).toContainText(number);

  await page.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByText("Approved. The quote can now be sent.")).toBeVisible();
});

test("Meera marks it sent and the revision PDF is a real PDF", async ({ page }) => {
  expect(quotePath, "the draft from the first step").not.toBe("");
  await signInAs(page, "MEERA");
  await page.goto(quotePath);

  await page.getByTestId("quote-commands").getByRole("button", { name: "Mark as sent" }).click();
  const pdfLink = page.getByRole("link", { name: "PDF of revision 1" });
  await expect(pdfLink).toBeVisible();

  const href = await pdfLink.getAttribute("href");
  expect(href).toMatch(/^\/api\/v1\/sales\/quotes\/[0-9a-f-]{36}\/revisions\/1\/document\.pdf$/);
  const response = await page.request.get(href!);
  expect(response.status()).toBe(200);
  expect(response.headers()["content-type"]).toContain("application/pdf");
  expect((await response.body()).subarray(0, 5).toString()).toBe("%PDF-");
});
