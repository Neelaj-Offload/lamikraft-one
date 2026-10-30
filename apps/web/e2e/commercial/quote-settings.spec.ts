import { expect, test } from "@playwright/test";
import { onlyOnProjects, signInAs } from "../support/world";

/** Quote settings (UI-92, API-35): numbering previews never allocate a number. Run by the integrator. */

test("preview_next_number_without_allocation", async ({ page }) => {
  onlyOnProjects("desktop");
  await signInAs(page, "SAHIL");
  await page.goto("/settings/quotes");
  const preview = page.getByText(/LK-QT-\d{4}-\d{4}/).first();
  await expect(preview).toBeVisible();
  const first = await preview.textContent();
  await page.reload();
  await expect(page.getByText(first ?? "")).toBeVisible();
});
