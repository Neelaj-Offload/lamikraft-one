import { expect, test } from "@playwright/test";
import { shoot } from "../support/evidence";
import { enrolAuthenticator, freshCode } from "../support/mfa";
import { onlyOnProjects, signInAs } from "../support/world";

/**
 * Scenario M (migration and backup parts) through the UI (PLAN Slice 5; the migration lane left e2e to the Slice-5
 * merge). `npm run test:e2e` runs, after seeding the e2e database, `lk migration dry-run` over the synthetic legacy
 * export (`backend/tests/fixtures/legacy_export`), `lk backup create` and `lk backup restore-rehearsal`, so the world
 * holds one dry run and one rehearsed backup. Priya (admin) enrols an authenticator, signs in again, confirms with a
 * code at the step-up (migration reports and backups are MFA-flagged reads) and reads: the run's reconciliation by
 * collection (every row accounted for), quote totals by currency, no stock from legacy challans, the quarantine; and
 * Settings › Backups with the passed rehearsal and its checks (tenant isolation fails closed, temporary database
 * dropped). Desktop only.
 */

test.describe.configure({ mode: "serial" });

let secret = "";

test.beforeAll(() => {
  onlyOnProjects("desktop");
});

// a fresh authenticator code can mean waiting for the next 30-second step
test.beforeEach(() => test.setTimeout(120_000));

test("Priya confirms with her authenticator and reads the dry run", async ({ page }) => {
  await signInAs(page, "PRIYA");
  secret = await enrolAuthenticator(page);
  // a fresh session is not MFA-verified: the report asks for a code first
  await signInAs(page, "PRIYA");
  await page.goto("/settings/migration");
  await page.getByRole("button", { name: "Confirm and show" }).click();
  const dialog = page.getByRole("dialog", { name: "Confirm it is you" });
  await dialog.getByRole("textbox", { name: "Authenticator code" }).fill(await freshCode(page, secret));
  await dialog.getByRole("button", { name: "Confirm and continue" }).click();
  await expect(dialog).toHaveCount(0);

  const latest = page.getByRole("region", { name: "Latest run" });
  await expect(latest).toBeVisible();
  await expect(latest).toContainText("Every row accounted for");
  await expect(page.getByRole("table", { name: "Migration runs, newest first" })).toContainText("Dry run");
  await expect(page.getByRole("region", { name: "Candidate customer links" })).toContainText("To review");

  await page.getByRole("table", { name: "Migration runs, newest first" }).getByRole("link").first().click();
  await expect(page).toHaveURL(/\/settings\/migration\/runs\/[0-9a-f-]{36}$/);
  await expect(page.getByRole("table", { name: "Rows per legacy collection" })).toBeVisible();
  await expect(page.getByRole("table", { name: "Legacy quote totals by currency" })).toContainText("EUR");
  const documents = page.getByRole("region", { name: "Legacy documents and people" });
  await expect(documents).toContainText("Stock movements planned from legacy challans");
  await expect(page.getByRole("table", { name: "Issues of this run" })).toBeVisible();
  // checkpoint-6 evidence (cp6 only), in this MFA-verified session
  const runPath = new URL(page.url()).pathname;
  await shoot(page, "settings-migration", "/settings/migration");
  await shoot(page, "migration-run", runPath);
  await shoot(page, "settings-backups", "/settings/backups");
});

test("Settings › Backups shows the rehearsed backup and its checks", async ({ page }) => {
  test.skip(!secret, "needs the authenticator from the previous test");
  await signInAs(page, "PRIYA");
  await page.goto("/settings/backups");
  const confirm = page.getByRole("button", { name: "Confirm and show" });
  if (await confirm.isVisible().catch(() => false)) {
    await confirm.click();
    const dialog = page.getByRole("dialog", { name: "Confirm it is you" });
    await dialog.getByRole("textbox", { name: "Authenticator code" }).fill(await freshCode(page, secret));
    await dialog.getByRole("button", { name: "Confirm and continue" }).click();
  }
  await expect(page.getByRole("region", { name: "Last backup" })).toBeVisible();
  const rehearsal = page.getByRole("region", { name: "Last restore rehearsal" });
  await expect(rehearsal).toContainText("Passed");
  const checks = page.getByRole("table", { name: "Verification queries of the last rehearsal" });
  for (const check of ["Dump checksum", "Tenant isolation fails closed", "Temporary database dropped"]) await expect(checks).toContainText(check);
});
