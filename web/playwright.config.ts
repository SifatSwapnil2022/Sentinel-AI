import { defineConfig, devices } from "@playwright/test";

// CI installs Playwright's own browser. Where its download is blocked, point CHROMIUM_PATH at any
// local Chromium binary.
const executablePath = process.env.CHROMIUM_PATH;
const launchOptions = executablePath
  ? { executablePath, args: ["--no-sandbox", "--disable-gpu"] }
  : {};

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  // A sandboxed Chromium (CHROMIUM_PATH) is less stable under load than Playwright's own build.
  ...(executablePath ? { workers: 2 } : {}),
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: "http://localhost:4173",
    trace: "retain-on-failure",
    launchOptions,
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1360, height: 900 } } },
    { name: "phone", use: { ...devices["Pixel 7"], launchOptions } },
  ],
  webServer: {
    command: "npm run build && npm run preview",
    url: "http://localhost:4173",
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
  },
});
