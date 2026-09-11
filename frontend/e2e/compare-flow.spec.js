// @ts-check
import { test, expect } from "@playwright/test";
import path from "node:path";
import fs from "node:fs";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ATTENDANCE_FIXTURE = path.join(
  __dirname, "..", "..", "backend", "tests", "fixtures", "sample_attendance.xlsx"
);
const CLIENT_FIXTURE = path.join(
  __dirname, "..", "..", "backend", "tests", "fixtures", "sample_client_work.xlsx"
);

const FAKE_COMPARE_RESPONSE = {
  summary: {
    total_records_compared: 3,
    matches: 1,
    mismatches: 2,
    review_required: 1,
  },
  mismatches: [
    {
      id: "H285491",
      employee_name: "Abdul Hakeem Habeeb Rahman",
      file1_total_hours: 176,
      file2_hours: 72,
      difference: 104,
      status: "Mismatch",
      severity: "HIGH",
      reason: "iLink Timesheet total 176 vs Client total 72 - difference 104 (iLink Timesheet higher).",
      recommendation: "Reconcile the logged hours against the source records.",
    },
    {
      id: "H324723",
      employee_name: "Abbas Ali Pathan",
      file1_total_hours: 29.7,
      file2_hours: null,
      difference: null,
      status: "Missing in Client",
      severity: "MEDIUM",
      reason: "ID exists in iLink Timesheet but not in Client.",
      recommendation: "Confirm whether the Client entry is missing.",
    },
  ],
  matched: [
    {
      id: "H100001",
      employee_name: "Test Match",
      file1_total_hours: 40,
      file2_hours: 40,
      difference: 0,
      status: "Match",
      severity: "MATCH",
      reason: "Hours match.",
      recommendation: "",
    },
  ],
  report_id: "e2e-fake-report-id",
  client_display_name: "Client",
};

/** Intercept POST /api/compare and return a fixed, known response instead
 * of letting the real backend call Groq. */
async function mockCompareEndpoint(page) {
  await page.route("**/api/compare", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(FAKE_COMPARE_RESPONSE),
    });
  });
}

/** Intercept the report download so clicking "Download Excel Report" doesn't
 * 404 against a report_id that was never actually written to disk (since
 * the real /api/compare call, and therefore the real report_writer call,
 * never ran). Reuses an existing valid .xlsx fixture as the response body
 * -- the tests only assert it's a real xlsx (starts with "PK") and that the
 * filename pattern is correct, not its contents. */
async function mockDownloadEndpoint(page) {
  const fileBytes = fs.readFileSync(ATTENDANCE_FIXTURE);
  await page.route("**/api/reports/**/download", async (route) => {
    await route.fulfill({
      status: 200,
      contentType:
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      headers: {
        "content-disposition":
          'attachment; filename="hours_comparison_report_20260828_120000.xlsx"',
      },
      body: fileBytes,
    });
  });
}

test.describe("Compare Files workflow", () => {
  test("full happy path: upload both files, pick identifiers, compare, download", async ({ page }) => {
    await mockCompareEndpoint(page);
    await mockDownloadEndpoint(page);

    await page.goto("/");

    // --- Upload the two fixture files -------------------------------------
    const attendanceInput = page
      .getByRole("button", { name: /iLink Timesheet/i })
      .locator('input[type="file"]');
    const clientInput = page
      .getByRole("button", { name: /Client File/i })
      .locator('input[type="file"]');

    await attendanceInput.setInputFiles(ATTENDANCE_FIXTURE);
    await clientInput.setInputFiles(CLIENT_FIXTURE);

    await expect(page.getByText("sample_attendance.xlsx")).toBeVisible();
    await expect(page.getByText("sample_client_work.xlsx")).toBeVisible();

    // --- Wait for column detection to finish, then pick identifiers -------
    // Column detection (/api/columns) is NOT mocked -- it doesn't touch the
    // LLM at all, so it's fine (and better coverage) to let it run for real.
    const attendanceSelect = page.locator("#attendance-key-column");
    const clientSelect = page.locator("#client-key-column");

    await expect(attendanceSelect).toBeEnabled({ timeout: 10_000 });
    await expect(clientSelect).toBeEnabled({ timeout: 10_000 });

    await attendanceSelect.selectOption({ label: "Employee Name" });
    await clientSelect.selectOption({ label: "Full Name" });

    // --- Run the comparison -------------------------------------------------
    const compareButton = page.getByRole("button", { name: /Compare Files/i });
    await expect(compareButton).toBeEnabled();
    await compareButton.click();

    // Mocked response returns instantly, so this should resolve well within
    // the default timeout -- no need to pad it for real LLM latency here.
    await expect(page.getByText("Total Compared")).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText("Matches", { exact: true })).toBeVisible();
    await expect(page.getByText("Mismatches", { exact: true })).toBeVisible();
    // Confirm the table actually renders real row data from the response
    // (name, hours, status) -- not just that the summary counters showed up.
    await expect(page.getByText("Abdul Hakeem Habeeb Rahman")).toBeVisible();
    await expect(page.getByText("176.00h")).toBeVisible();

    // --- Download link should now be present --------------------------------
    const downloadLink = page.getByRole("link", { name: /Download Excel Report/i });
    await expect(downloadLink).toBeVisible();

    const [download] = await Promise.all([
      page.waitForEvent("download"),
      downloadLink.click(),
    ]);
    expect(download.suggestedFilename()).toMatch(/^hours_comparison_report_.*\.xlsx$/);
  });

  test("Compare button stays disabled until both files and both identifiers are set", async ({ page }) => {
    // No /api/compare call happens in this test -- nothing to mock.
    await page.goto("/");

    const compareButton = page.getByRole("button", { name: /Compare Files/i });
    await expect(compareButton).toBeDisabled();

    const attendanceInput = page
      .getByRole("button", { name: /iLink Timesheet/i })
      .locator('input[type="file"]');
    await attendanceInput.setInputFiles(ATTENDANCE_FIXTURE);

    await expect(compareButton).toBeDisabled();

    const clientInput = page
      .getByRole("button", { name: /Client File/i })
      .locator('input[type="file"]');
    await clientInput.setInputFiles(CLIENT_FIXTURE);

    await expect(compareButton).toBeDisabled();

    await page.locator("#attendance-key-column").selectOption({ label: "Employee Name" });
    await expect(compareButton).toBeDisabled(); // only one side chosen

    await page.locator("#client-key-column").selectOption({ label: "Full Name" });
    await expect(compareButton).toBeEnabled(); // now both are set
  });

  test("choosing a new file clears any previous comparison result", async ({ page }) => {
    await mockCompareEndpoint(page);

    await page.goto("/");

    const attendanceInput = page
      .getByRole("button", { name: /iLink Timesheet/i })
      .locator('input[type="file"]');
    const clientInput = page
      .getByRole("button", { name: /Client File/i })
      .locator('input[type="file"]');

    await attendanceInput.setInputFiles(ATTENDANCE_FIXTURE);
    await clientInput.setInputFiles(CLIENT_FIXTURE);
    await page.locator("#attendance-key-column").selectOption({ label: "Employee Name" });
    await page.locator("#client-key-column").selectOption({ label: "Full Name" });

    await page.getByRole("button", { name: /Compare Files/i }).click();
    await expect(page.getByText("Total Compared")).toBeVisible({ timeout: 10_000 });

    // Re-selecting a DIFFERENT file on the attendance side should invalidate
    // the stale result (see handleFileSelected's setResult(null) in
    // ComparePage.jsx).
    await attendanceInput.setInputFiles(CLIENT_FIXTURE);
    await expect(page.getByText("Total Compared")).not.toBeVisible();
  });

  test("rejects a non-Excel file with a visible error", async ({ page }) => {
    // No /api/compare call happens in this test -- it never gets past
    // column detection -- so nothing to mock.
    await page.goto("/");

    const attendanceInput = page
      .getByRole("button", { name: /iLink Timesheet/i })
      .locator('input[type="file"]');

    await attendanceInput.setInputFiles({
      name: "notes.txt",
      mimeType: "text/plain",
      buffer: Buffer.from("just some text"),
    });

    await expect(page.getByText(/not an Excel file/i)).toBeVisible({ timeout: 10_000 });
  });
});

/**
 * Opt-in live integration test: exercises the REAL backend + REAL Groq
 * call, end to end, with no mocking at all. Skipped by default -- only
 * runs when you explicitly set RUN_LIVE_LLM_E2E=1 in the environment
 * before starting Playwright. Use this by hand occasionally (backend must
 * be running with a valid GROQ_API_KEY in backend/.env); don't rely on it
 * in CI for the same reasons noted at the top of this file.
 */
test.describe("Live LLM integration (opt-in, not run in CI)", () => {
  test.skip(
    !process.env.RUN_LIVE_LLM_E2E,
    "Set RUN_LIVE_LLM_E2E=1 to run this against the real Groq API"
  );

  test("full happy path against the real backend and real LLM", async ({ page }) => {
    await page.goto("/");

    const attendanceInput = page
      .getByRole("button", { name: /iLink Timesheet/i })
      .locator('input[type="file"]');
    const clientInput = page
      .getByRole("button", { name: /Client File/i })
      .locator('input[type="file"]');

    await attendanceInput.setInputFiles(ATTENDANCE_FIXTURE);
    await clientInput.setInputFiles(CLIENT_FIXTURE);

    const attendanceSelect = page.locator("#attendance-key-column");
    const clientSelect = page.locator("#client-key-column");
    await expect(attendanceSelect).toBeEnabled({ timeout: 10_000 });
    await expect(clientSelect).toBeEnabled({ timeout: 10_000 });
    await attendanceSelect.selectOption({ label: "Employee Name" });
    await clientSelect.selectOption({ label: "Full Name" });

    await page.getByRole("button", { name: /Compare Files/i }).click();

    // Real LLM latency (plus small batch sizes) can be slow -- generous
    // timeout here on purpose, unlike the mocked tests above.
    await expect(page.getByText("Total Compared")).toBeVisible({ timeout: 60_000 });
  });
});