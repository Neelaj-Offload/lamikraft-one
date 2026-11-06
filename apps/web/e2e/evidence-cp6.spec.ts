import { test } from "@playwright/test";
import { CP6, shoot } from "./support/evidence";
import { loadWorld, onlyOnProjects, ref, signInAs, type PersonKey, type World } from "./support/world";

/**
 * Checkpoint-6 evidence (docs/evidence/checkpoint-6/): the screens the Slice-5 lanes added that need no record created
 * by a scenario (the finance area, the Maison receipt, ageing, exceptions, accounting sync, the what-if screen, a cut
 * plan with its offcut choice, the samples list) at 1440 and 390 px, light and dark, on the --slice 5 demo world.
 * The invoice workspace, a sample's lineage and Settings › Migration / Backups (behind an MFA step-up) are shot by
 * `scenarios/m-finance`, `scenarios/o-offcut-lineage-what-if` and `scenarios/m-migration` in the same run. Opt-in:
 * `LK_E2E_EVIDENCE=cp6 npm run test:e2e -- --workers=1`.
 */

test.skip(!CP6, "checkpoint-6 evidence runs only with LK_E2E_EVIDENCE=cp6");
test.describe.configure({ mode: "serial" });

let world: World;

test.beforeAll(async ({ request }) => {
  onlyOnProjects("desktop");
  world = await loadWorld(request);
});

type Shot = { name: string; person: PersonKey; url: () => string | null };

const SHOTS: readonly Shot[] = [
  { name: "finance-overview", person: "ANANYA", url: () => "/finance" },
  { name: "finance-invoices", person: "ANANYA", url: () => "/finance/invoices" },
  { name: "finance-receipts", person: "ANANYA", url: () => "/finance/receipts" },
  { name: "finance-receipt", person: "ANANYA", url: () => (ref(world, "RCPT_MAISON") ? `/finance/receipts/${ref(world, "RCPT_MAISON")}` : null) },
  { name: "finance-ageing", person: "ANANYA", url: () => "/finance/ageing" },
  { name: "finance-exceptions", person: "ANANYA", url: () => "/finance/exceptions" },
  { name: "finance-accounting-sync", person: "ANANYA", url: () => "/finance/accounting-sync" },
  { name: "production-what-if", person: "DEEPA", url: () => "/operations/production/what-if" },
  { name: "cut-plan-offcuts", person: "DEEPA", url: () => (ref(world, "CUT_PLAN_WALNUT") ? `/operations/cutting/${ref(world, "CUT_PLAN_WALNUT")}` : null) },
  { name: "samples", person: "MEERA", url: () => "/sales/samples" },
];

for (const shot of SHOTS) {
  test(`checkpoint-6 evidence ${shot.name}`, async ({ page }) => {
    test.setTimeout(180_000);
    const url = shot.url();
    test.skip(url === null, `no fixture record for ${shot.name}`);
    await signInAs(page, shot.person);
    await shoot(page, shot.name, url!);
  });
}
