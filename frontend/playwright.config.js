// @ts-check
import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright config for end-to-end UI tests against the real running app.
 *
 * This drives the app exactly like a user would: real browser, real DOM,
 * real network calls to the FastAPI backend. It does NOT mock the backend --
 * that's the point (see e2e/README.md for why, and for the alternative
 * "frontend-only, backend mocked" approach if you want faster/more isolated
 * runs instead).
 *
 * Prerequisites before running `npx playwright test`:
 *   1. Backend running:  cd backend && uvicorn app.main:app --port 8000
 *   2. Frontend running: cd frontend && npm run dev
 *      (or let `webServer` below start it automatically -- see the
 *      commented-out block)
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  expect: { timeout: 5_000 },
  fullyParallel: false, // the backend has no test isolation between runs
  retries: 0,
  reporter: [["html", { open: "never" }], ["list"]],

  use: {
    baseURL: process.env.E2E_BASE_URL || "http://localhost:5173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },

  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],

  // Uncomment to have Playwright start the Vite dev server itself:
  // webServer: {
  //   command: "npm run dev",
  //   url: "http://localhost:5173",
  //   reuseExistingServer: !process.env.CI,
  // },
});
