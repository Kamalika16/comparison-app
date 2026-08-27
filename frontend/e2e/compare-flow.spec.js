// @ts-check
import { test, expect } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ATTENDANCE_FIXTURE = path.join(
  __dirname, "..", "..", "backend", "tests", "fixtures", "sample_attendance.xlsx"
);
const CLIENT_FIXTURE = path.join(
  __dirname, "..", "..", "backend", "tests", "fixtures", "sample_client_work.xlsx"
);

/**
 * These tests drive the actual React app in a real browser and hit the
 * real FastAPI backend (see playwright.config.js). Selectors deliberately
 * use accessible roles/labels/text -- the same attributes a screen reader
 * user would rely on -- rather than brittle CSS classes, so the tests keep
 * working through most visual refactors.
 */

test.describe("Compare Files workflow", () => {
  test("full happy path: upload both files, pick identifiers, compare, download", async ({ page }) => {
    await page.goto("/");

    // --- Upload the two fixture files -------------------------------------
    // Each FileUploader renders a hidden <input type="file"> inside a
    // role="button" container labelled by the `label` prop passed from
    // ComparePage.jsx ("iLink Attendance" / "Client Worksheet").
    const attendanceInput = page
      .getByRole("button", { name: /iLink Attendance/i })
      .locator('input[type="file"]');
    const clientInput = page
      .getByRole("button", { name: /Client Worksheet/i })
      .locator('input[type="file"]');

    await attendanceInput.setInputFiles(ATTENDANCE_FIXTURE);
    await clientInput.setInputFiles(CLIENT_FIXTURE);

    // Filenames should now be visible in each dropzone.
    await expect(page.getByText("sample_attendance.xlsx")).toBeVisible();
    await expect(page.getByText("sample_client_work.xlsx")).toBeVisible();

    // --- Wait for column detection to finish, then pick identifiers -------
    // Both ColumnSelectors share the same visible label ("Primary Identifier"),
    // so getByLabel() alone can't tell them apart -- select by the actual
    // element id instead (id={`${id}-key-column`} in ColumnSelector.jsx).
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

    // Backend responds; results should render.
    await expect(page.getByText("Total Compared")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText("Matches", { exact: true })).toBeVisible();
    await expect(page.getByText("Mismatches", { exact: true })).toBeVisible();

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
    await page.goto("/");

    const compareButton = page.getByRole("button", { name: /Compare Files/i });
    await expect(compareButton).toBeDisabled();

    const attendanceInput = page
      .getByRole("button", { name: /iLink Attendance/i })
      .locator('input[type="file"]');
    await attendanceInput.setInputFiles(ATTENDANCE_FIXTURE);

    // Only one file selected -> still disabled.
    await expect(compareButton).toBeDisabled();

    const clientInput = page
      .getByRole("button", { name: /Client Worksheet/i })
      .locator('input[type="file"]');
    await clientInput.setInputFiles(CLIENT_FIXTURE);

    // Both files present, but no identifier columns chosen yet -> still disabled.
    await expect(compareButton).toBeDisabled();

    await page.locator("#attendance-key-column").selectOption({ label: "Employee Name" });
    await expect(compareButton).toBeDisabled(); // only one side chosen

    await page.locator("#client-key-column").selectOption({ label: "Full Name" });
    await expect(compareButton).toBeEnabled(); // now both are set
  });

  test("choosing a new file clears any previous comparison result", async ({ page }) => {
    await page.goto("/");

    const attendanceInput = page
      .getByRole("button", { name: /iLink Attendance/i })
      .locator('input[type="file"]');
    const clientInput = page
      .getByRole("button", { name: /Client Worksheet/i })
      .locator('input[type="file"]');

    await attendanceInput.setInputFiles(ATTENDANCE_FIXTURE);
    await clientInput.setInputFiles(CLIENT_FIXTURE);
    await page.locator("#attendance-key-column").selectOption({ label: "Employee Name" });
    await page.locator("#client-key-column").selectOption({ label: "Full Name" });

    await page.getByRole("button", { name: /Compare Files/i }).click();
    await expect(page.getByText("Total Compared")).toBeVisible({ timeout: 15_000 });

    // Re-selecting a DIFFERENT file on the attendance side should invalidate
    // the stale result (see handleFileSelected's setResult(null) in
    // ComparePage.jsx). Using a different fixture here -- rather than
    // re-selecting the identical file -- avoids relying on browser change-
    // event behavior for a byte-identical re-selection, which is an
    // ambiguous edge case unrelated to what this test is actually checking.
    await attendanceInput.setInputFiles(CLIENT_FIXTURE);
    await expect(page.getByText("Total Compared")).not.toBeVisible();
  });

  test("rejects a non-Excel file with a visible error", async ({ page }) => {
    await page.goto("/");

    // Build a small in-memory .txt "upload" to exercise the extension check
    // enforced both client-side (accept=".xlsx,.xls,.csv") and, more
    // importantly, server-side in _save_upload (routes/compare.py).
    const attendanceInput = page
      .getByRole("button", { name: /iLink Attendance/i })
      .locator('input[type="file"]');

    await attendanceInput.setInputFiles({
      name: "notes.txt",
      mimeType: "text/plain",
      buffer: Buffer.from("just some text"),
    });

    // The <input accept> attribute doesn't block programmatic setInputFiles,
    // so this reaches POST /api/columns and should surface the backend's
    // 400 error message inside the ColumnSelector's error slot.
    await expect(page.getByText(/not an Excel file/i)).toBeVisible({ timeout: 10_000 });
  });
});