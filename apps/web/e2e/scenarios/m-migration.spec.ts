import { expect, test, type BrowserContext } from "@playwright/test";
import { shoot } from "../support/evidence";
import { enrolAuthenticator, freshCode } from "../support/mfa";
import { onlyOnProjects, signInAs, signInWithDemoLink } from "../support/world";

/**
 * Scenario M (migration and backup parts) through the UI (PLAN Slice 5; the migration lane left e2e to the Slice-5
 * merge). `npm run test:e2e` runs, after seeding the e2e database, `lk migration dry-run` over the synthetic legacy
 * export (`backend/tests/fixtures/legacy_export`), `lk backup create` and `lk backup restore-rehearsal`, so the world
 * holds one dry run and one rehearsed backup. Priya (admin) opens a Demo-link session, enrols an authenticator in another session, then confirms the first with a
 * code at the step-up (migration reports and backups are MFA-flagged reads) and reads: the run's reconciliation by
 * collection (every row accounted for), quote totals by currency, no stock from legacy challans, the quarantine; and
 * Settings › Backups with the passed rehearsal and its checks (tenant isolation fails closed, temporary database
 * dropped). Desktop only.
 */

test.describe.configure({ mode: "serial" });

let verifiedCookies: Awaited<ReturnType<BrowserContext["cookies"]>> = [];

test.beforeAll(() => {
  onlyOnProjects("desktop");
});

// a fresh authenticator code can mean waiting for the next 30-second step
test.beforeEach(() => test.setTimeout(120_000));

test("Priya confirms with her authenticator and reads the dry run", async ({ page }) => {
  // Keep a real, lower-strength session opened before enrolment. Test-support sessions deliberately include MFA.
  await signInWithDemoLink(page, "PRIYA");
  const unverifiedCookies = await page.context().cookies();
  await signInAs(page, "PRIYA");
  const secret = await enrolAuthenticator(page);
  await page.context().clearCookies();
  await page.context().addCookies(unverifiedCookies);
  const refused = await page.request.get("/api/v1/migration/runs");
  expect(refused.status()).toBe(401);
  expect(((await refused.json()) as { code: string }).code).toBe("mfa_required");
  await page.goto("/settings/migration");
  await page.getByRole("button", { name: "Confirm and show" }).click();
  const dialog = page.getByRole("dialog", { name: "Confirm it is you" });
  await dialog.getByRole("textbox", { name: "Authenticator code" }).fill(await freshCode(page, secret));
  await dialog.getByRole("button", { name: "Confirm and continue" }).click();
  await expect(dialog).toHaveCount(0);

  const latest = page.getByRole("region", { name: "Latest run" });
  await expect(latest).toBeVisible();
  await expect(latest).toContainText("Completed");
  await expect(page.getByRole("table", { name: "Migration runs, newest first" })).toContainText("Dry run");
  await expect(page.getByRole("region", { name: "Candidate customer links" })).toContainText("To review");

  await page.getByRole("table", { name: "Migration runs, newest first" }).getByRole("link").first().click();
  await expect(page).toHaveURL(/\/settings\/migration\/runs\/[0-9a-f-]{36}$/);
  await expect(page.getByRole("table", { name: "Rows per legacy collection" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Source" })).toContainText("Every row accounted for");
  await expect(page.getByRole("table", { name: "Legacy quote totals by currency" })).toContainText("EUR");
  const documents = page.getByRole("region", { name: "Legacy documents and people" });
  await expect(documents).toContainText("Stock movements planned from legacy challans");
  await expect(page.getByRole("table", { name: "Issues of this run" })).toBeVisible();
  // checkpoint-6 evidence (cp6 only), in this MFA-verified session
  const runPath = new URL(page.url()).pathname;
  await shoot(page, "settings-migration", "/settings/migration");
  await shoot(page, "migration-run", runPath);
  await shoot(page, "settings-backups", "/settings/backups");
  verifiedCookies = await page.context().cookies();
});

test("Settings › Backups shows the rehearsed backup and its checks", async ({ page }) => {
  expect(verifiedCookies.length, "session verified with the real authenticator in the first test").toBeGreaterThan(0);
  await page.context().addCookies(verifiedCookies);
  await page.goto("/settings/backups");
  await expect(page.getByRole("region", { name: "Last backup" })).toBeVisible();
  const rehearsal = page.getByRole("region", { name: "Last restore rehearsal" });
  await expect(rehearsal).toContainText("Passed");
  const checks = page.getByRole("table", { name: "Verification queries of the last rehearsal" });
  for (const check of ["Dump checksum", "Tenant isolation fails closed", "Temporary database dropped"]) await expect(checks).toContainText(check);
});
