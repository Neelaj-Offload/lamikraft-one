import { expect, test } from "@playwright/test";
import { loadWorld, onlyOnProjects, signInAs } from "../support/world";

/**
 * ai-routing §4.2 / §9 `masked_regions_are_blacked_out_and_capture_is_explicit`: nothing is captured
 * until "Look at my screen" is pressed; the capture comes from the app's own DOM (never
 * getDisplayMedia); a `data-restricted` region is an opaque block in the uploaded WebP while the
 * live page keeps showing it; the image is at most 1568 px and 1.5 MB; the chip is removable; a
 * question is answered from the screenshot (Demo) and the screenshot is used once. Written by the
 * voice-vision lane.
 */

const chip = (page: import("@playwright/test").Page) => page.getByRole("group", { name: "Voice and screen" }).getByText("Masked screenshot attached");

test.beforeAll(async ({ request }) => {
  onlyOnProjects("desktop", "phone");
  await loadWorld(request);
});

test("masked_regions_are_blacked_out_and_capture_is_explicit", async ({ page }) => {
  await page.addInitScript(() => {
    // keep the bytes of each uploaded capture for the pixel check (a FormData blob body is not exposed to Playwright)
    const append = FormData.prototype.append;
    FormData.prototype.append = function (this: FormData, name: string, value: string | Blob, filename?: string) {
      if (value instanceof Blob && filename?.startsWith("screen.")) {
        void value.arrayBuffer().then((buffer) => {
          (window as unknown as { __capture: number[] }).__capture = Array.from(new Uint8Array(buffer));
        });
      }
      (append as (this: FormData, ...args: unknown[]) => void).apply(this, filename === undefined ? [name, value] : [name, value, filename]);
    } as typeof FormData.prototype.append;
    (window as unknown as { __displayMediaCalls: number }).__displayMediaCalls = 0;
    if (navigator.mediaDevices) {
      navigator.mediaDevices.getDisplayMedia = () => {
        (window as unknown as { __displayMediaCalls: number }).__displayMediaCalls += 1;
        return Promise.reject(new DOMException("not allowed", "NotAllowedError"));
      };
    }
  });
  const uploads: { url: string }[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().includes("/api/v1/vision/screen-captures")) uploads.push({ url: request.url() });
  });

  await signInAs(page, "MEERA");
  await page.goto("/today");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  // a restricted region the capture must black out (costing and bank details carry the same attribute)
  await page.evaluate(() => {
    const box = document.createElement("div");
    box.setAttribute("data-restricted", "true");
    box.id = "e2e-restricted";
    box.textContent = "COST-SENTINEL 123.45";
    box.style.cssText = "position:fixed;left:16px;top:120px;width:240px;height:80px;background:#ffffff;color:#000;z-index:50";
    document.body.appendChild(box);
  });
  await page.waitForTimeout(500);
  expect(uploads, "nothing is captured in the background").toHaveLength(0);

  await page.getByRole("button", { name: "Look at my screen" }).click();
  await expect(chip(page)).toBeVisible({ timeout: 15_000 });
  expect(uploads).toHaveLength(1);
  const url = new URL(uploads[0]!.url);
  expect(Number(url.searchParams.get("masked_count"))).toBeGreaterThanOrEqual(1);
  expect(await page.evaluate(() => (window as unknown as { __displayMediaCalls: number }).__displayMediaCalls)).toBe(0);
  await expect(page.locator("#e2e-restricted")).toHaveText("COST-SENTINEL 123.45"); // the live page is untouched

  // decode the uploaded image in the page and sample the restricted region: it must be the opaque mask colour
  const sample = await page.evaluate(async () => {
    const bytes = (window as unknown as { __capture: number[] }).__capture;
    const blob = new Blob([new Uint8Array(bytes)]);
    const bitmap = await createImageBitmap(blob);
    const scale = bitmap.width / window.innerWidth;
    const canvas = document.createElement("canvas");
    canvas.width = bitmap.width;
    canvas.height = bitmap.height;
    const context = canvas.getContext("2d")!;
    context.drawImage(bitmap, 0, 0);
    const rect = document.getElementById("e2e-restricted")!.getBoundingClientRect();
    const pixel = context.getImageData(Math.floor((rect.left + rect.width / 2) * scale), Math.floor((rect.top + rect.height / 2) * scale), 1, 1).data;
    return { width: bitmap.width, height: bitmap.height, size: bytes.length, pixel: Array.from(pixel) };
  });
  expect(sample.size).toBeLessThanOrEqual(1_572_864);
  expect(Math.max(sample.width, sample.height)).toBeLessThanOrEqual(1568);
  const [r, g, b] = sample.pixel;
  expect(r! + g! + b!, `masked pixel ${sample.pixel.join(",")} is dark, not the white restricted box`).toBeLessThan(200);

  // remove, attach again, then ask: answered from the screenshot (Demo) and used once
  await page.getByRole("button", { name: "Remove the screenshot" }).click();
  await expect(chip(page)).toHaveCount(0);
  await page.getByRole("button", { name: "Look at my screen" }).click();
  await expect(chip(page)).toBeVisible({ timeout: 15_000 });
  await page.getByRole("textbox", { name: /Ask about your day/ }).fill("What is on my screen?");
  await page.getByRole("button", { name: "Send", exact: true }).first().click();
  await expect(page.getByRole("region", { name: "About your screen" })).toContainText("You are in", { timeout: 15_000 });
  await expect(chip(page)).toHaveCount(0);
});
