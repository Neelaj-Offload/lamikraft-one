import { defineConfig, devices } from "@playwright/test";

const port = Number(process.env.LK_E2E_WEB_PORT ?? 3100);
const baseURL = `http://127.0.0.1:${port}`;

/**
 * End-to-end configuration. The web server is the production build
 * (`npm run build` first); the FastAPI test server is started by the root
 * `npm run test:e2e` orchestration and reached through the /api rewrite.
 * Set LK_E2E_EXTERNAL_WEB=1 to test an already running web server instead.
 */
export default defineConfig({
  testDir: "./e2e",
  outputDir: "./test-results/artifacts",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: 2,
  timeout: 30_000,
  expect: { timeout: 5_000 },
  reporter: [
    ["list"],
    ["html", { outputFolder: "./test-results/html-report", open: "never" }],
  ],
  use: {
    baseURL,
    browserName: "chromium",
    locale: "en-IN",
    timezoneId: "Asia/Kolkata",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    launchOptions: {
      args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"],
    },
  },
  projects: [
    {
      name: "desktop",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 900 },
      },
    },
    {
      name: "tablet",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 834, height: 1112 },
        deviceScaleFactor: 2,
        hasTouch: true,
      },
    },
    {
      name: "phone",
      use: {
        ...devices["Pixel 7"],
        viewport: { width: 390, height: 844 },
        deviceScaleFactor: 3,
        isMobile: true,
        hasTouch: true,
      },
    },
  ],
  webServer: process.env.LK_E2E_EXTERNAL_WEB
    ? undefined
    : {
        command: `npm run start -- --port ${port}`,
        url: `${baseURL}/login`,
        reuseExistingServer: !process.env.CI,
        timeout: 120_000,
        stdout: "pipe",
        stderr: "pipe",
      },
});
