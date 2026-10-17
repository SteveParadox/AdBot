import { test, expect } from "@playwright/test";

test("natural-language objective uses observed links and returns cited evidence", async ({
  page,
}) => {
  await page.goto("/");
  await page
    .getByLabel("Workspace API key")
    .fill("e2e-local-key-000000000000000000000000");
  await page.getByRole("button", { name: "Connect workspace" }).click();
  await page.getByRole("button", { name: "AI Agent", exact: true }).click();
  await page
    .getByLabel("Task starting URL")
    .fill("http://127.0.0.1:8765/agent/news?layout=1");
  await page
    .getByLabel("Natural-language objective")
    .fill("Find the launch month for Orion AI and cite the source.");
  await page.getByLabel("I authorize browser automation on this URL.").check();
  await page.getByRole("button", { name: "Start agent task" }).click();
  await expect(
    page.getByRole("heading", { name: "Verified task result" }),
  ).toBeVisible({ timeout: 30000 });
  await expect(
    page
      .getByText("Orion AI will launch in November 2026.", { exact: true })
      .first(),
  ).toBeVisible();
  await expect(
    page.getByRole("img", { name: "Current agent browser page" }),
  ).toBeVisible();
  await expect(
    page.getByText("Fixture verifier found quoted source evidence", {
      exact: true,
    }),
  ).toBeVisible();
  await page.screenshot({
    path: "test-results/agent-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: "test-results/agent-mobile.png",
    fullPage: true,
  });
});
