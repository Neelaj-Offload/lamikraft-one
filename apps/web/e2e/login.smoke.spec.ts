import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const WCAG_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

/** Fails the test on uncaught page errors or console errors. */
function watchForErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(`console: ${message.text()}`);
  });
  return errors;
}

test.describe("login page smoke", () => {
  test("serves the sign-in page with security headers", async ({ page }) => {
    const errors = watchForErrors(page);
    const response = await page.goto("/login");

    expect(response?.status()).toBe(200);
    const headers = response!.headers();
    expect(headers["x-content-type-options"]).toBe("nosniff");
    expect(headers["referrer-policy"]).toBe("strict-origin-when-cross-origin");
    expect(headers["x-frame-options"]).toBe("DENY");
    expect(headers["permissions-policy"]).toContain("microphone=(self)");
    expect(headers["permissions-policy"]).toContain("camera=(self)");
    expect(headers["x-powered-by"]).toBeUndefined();

    await expect(page).toHaveTitle("Sign in · Lamikraft One");
    await expect(page.locator("html")).toHaveAttribute("lang", "en");
    await expect(page.getByRole("main")).toBeVisible();
    await expect(page.getByRole("heading", { level: 1, name: "Sign in" })).toBeVisible();
    expect(errors).toEqual([]);
  });

  test("uses the self-hosted Manrope face", async ({ page }) => {
    await page.goto("/login");
    await page.evaluate(() => document.fonts.ready);
    const family = await page.locator("body").evaluate((element) => getComputedStyle(element).fontFamily);
    expect(family).toMatch(/^"?Manrope Variable"?/);
    expect(await page.evaluate(() => document.fonts.check('16px "Manrope Variable"'))).toBe(true);
  });

  for (const theme of ["light", "dark"] as const) {
    test(`has no WCAG 2.2 AA violations in the ${theme} theme`, async ({ page, context, baseURL }) => {
      await context.addCookies([{ name: "lk_ui", value: `theme=${theme}&motion=reduced`, url: baseURL! }]);
      await page.goto("/login");

      await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
      await expect(page.locator("html")).toHaveAttribute("data-motion", "reduced");

      const results = await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze();
      expect(results.violations).toEqual([]);
    });
  }

  test("follows the OS colour scheme when no theme is chosen", async ({ page }) => {
    await page.emulateMedia({ colorScheme: "dark" });
    await page.goto("/login");

    await expect(page.locator("html")).not.toHaveAttribute("data-theme", /.+/);
    const background = await page.locator("body").evaluate((element) => getComputedStyle(element).backgroundColor);
    expect(background).toBe("rgb(17, 22, 19)");
  });
});
