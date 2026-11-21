import { test, expect } from "@playwright/test";

test("register target, launch crawl, inspect real persisted pages and screenshot", async ({
  page,
}) => {
  await page.goto("/");
  await page
    .getByLabel("Workspace API key")
    .fill("e2e-local-key-000000000000000000000000");
  await page.getByRole("button", { name: "Connect workspace" }).click();
  await expect(
    page.getByRole("heading", { name: "A clearer view of your web." }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Overview", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Add website" }).click();
  await page.getByRole("button", { name: "Add website" }).click();
  await page.getByLabel("Website name").fill("E2E fixture");
  await page.getByLabel("Starting URL").fill("http://127.0.0.1:8765/");
  await page.getByLabel("Allowed domains (comma separated)").fill("127.0.0.1");
  await page.getByLabel("Maximum pages", { exact: true }).fill("5");
  await page.getByLabel("Delay between pages (seconds)").fill("0.1");
  await page.getByText("Browser, limits, and URL rules").click();
  await page.getByLabel("screenshots", { exact: true }).check();
  await page
    .getByLabel(
      "I am authorized to automate this website and these destinations.",
    )
    .check();
  await page.getByRole("button", { name: "Save website" }).click();
  await expect(
    page.getByRole("heading", { name: "E2E fixture" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Jobs", exact: true }).click();
  await page
    .getByRole("combobox", { name: "Website", exact: true })
    .selectOption({ label: "E2E fixture" });
  await page.getByRole("button", { name: "Start job" }).click();
  await expect(
    page.getByText("Job completed", { exact: true }).first(),
  ).toBeVisible({ timeout: 30000 });
  await expect(
    page.getByText("About fixture", { exact: true }).first(),
  ).toBeVisible();
  await expect(
    page.getByRole("cell", { name: "404", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "View", exact: true }).first().click();
  await expect(
    page.getByRole("img", { name: "Captured website viewport" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Close screenshot" }).click();
  await expect(
    page.getByText("Isolated browser context launched"),
  ).toBeVisible();
  await page.screenshot({
    path: "test-results/job-monitor.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Schedules", exact: true }).click();
  await page
    .getByRole("combobox", { name: "Website", exact: true })
    .selectOption({ label: "E2E fixture" });
  await page.getByRole("button", { name: "Save schedule" }).click();
  await expect(
    page.getByRole("cell", { name: "0 8 * * *", exact: false }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Pause", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Resume", exact: true }),
  ).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: "test-results/mobile-schedules.png",
    fullPage: true,
  });
  await page.getByRole('button', {name: 'Disconnect', exact: true}).click();
  await expect(page.getByLabel('Workspace API key')).toBeVisible();
});
