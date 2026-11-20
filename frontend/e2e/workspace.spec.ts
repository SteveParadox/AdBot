import { test, expect, type Page } from "@playwright/test";
import { defaults } from "../src/api";

async function workspace(page: Page) {
  const now = Math.floor(Date.now() / 1000);
  const sites = ["Product catalog", "Newsroom"].map((name, index) => ({ id: `site-${index}`, name, base_url: `https://${index ? "news" : "catalog"}.example.org/`, allowed_domains: ["example.org"], configuration: defaults, created_at: now }));
  const jobs = ["completed", "running", "failed"].map((status, index) => ({ id: `job-${index}`, website_id: sites[index % 2].id, job_type: "crawl", status, pages_visited: index ? 8 : 24, created_at: now - 1200 * index, started_at: now - 1000, completed_at: status === "running" ? null : now, error_message: null, priority: 0, depends_on: null }));
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    let result: unknown = { items: [], total: 0 };
    if (path === "/api/websites") result = {items: sites, total: sites.length};
    else if (path === "/api/jobs") result = {items: jobs, total: jobs.length};
    else if (path === "/api/analytics/overview") result = {websites: 2, jobs: 14, pages: 1840, average_ms: 437, failure_rate: 1 / 14, scheduled_jobs: 3, scheduled_success_rate: 1, statuses: {completed: 12, running: 1, failed: 1}, daily_pages: Array.from({length: 30}, (_, index) => ({day: Math.floor(now / 86400) * 86400 - (29 - index) * 86400, count: 12 + (index * 13) % 52})), http_statuses: [{status: 200, count: 1824}, {status: 404, count: 16}]};
    await route.fulfill({json: result});
  });
  await page.goto("/");
  return async () => {
    await page.getByLabel("Workspace API key").fill("ui-fixture-key-not-a-real-secret-000000");
    await page.getByRole("button", {name: "Connect workspace"}).click();
    await expect(page.getByRole("heading", {name: "A clearer view of your web."})).toBeVisible();
  };
}

test("desktop navigation, filters, view preferences and quick actions", async ({page}) => {
  await page.setViewportSize({width: 1440, height: 1000});
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  const connect = await workspace(page);
  await page.screenshot({path: "test-results/workspace-login.png", fullPage: true});
  await connect();
  await expect(page.getByRole("button", {name: "30 days", exact: true})).toHaveAttribute("aria-pressed", "true");
  const fullActivityPath = await page.locator(".recharts-area-curve").getAttribute("d");
  await page.getByRole("button", {name: "7 days", exact: true}).click();
  await expect(page.locator(".recharts-area-curve")).not.toHaveAttribute("d", fullActivityPath!);
  await expect(page.getByRole("button", {name: "7 days", exact: true})).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByText("Pages recorded over the last 7 days")).toBeVisible();
  await page.screenshot({path: "test-results/workspace-desktop.png", fullPage: true});
  await page.keyboard.press("Control+k");
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await page.getByLabel("Find a page or action").fill("nonexistent");
  await expect(dialog.getByText(/No matches/)).toBeVisible();
  await page.getByLabel("Find a page or action").fill("website");
  await page.getByLabel("Find a page or action").press("ArrowUp");
  await expect(dialog.getByRole("button", {name: /^Websites/})).toBeFocused();
  await page.getByLabel("Find a page or action").focus();
  await page.getByLabel("Find a page or action").press("ArrowDown");
  await expect(dialog.getByRole("button", {name: /^Add website/})).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();
  await expect(page.getByRole("button", {name: "Search workspace", exact: true})).toBeFocused();
  await page.getByRole("button", {name: "Search workspace", exact: true}).click();
  await page.getByLabel("Find a page or action").fill("websites");
  await dialog.getByRole("button", {name: /^Websites/}).click();
  await page.getByLabel("Search websites").fill("catalog");
  await expect(page.getByRole("heading", {name: "Product catalog", exact: true})).toBeVisible();
  await expect(page.getByRole("heading", {name: "Newsroom", exact: true})).toHaveCount(0);
  await page.getByRole("button", {name: "List view", exact: true}).click();
  await expect(page.locator(".site-grid")).toHaveClass(/list-view/);
  await page.screenshot({path: "test-results/workspace-websites.png", fullPage: true});
  await page.getByLabel("Search websites").fill("not-found");
  await expect(page.getByText("No matching websites. Try a different name or domain.")).toBeVisible();
  await page.getByRole("button", {name: "Refresh workspace", exact: true}).click();
  await expect(page.getByRole("status").filter({hasText: "Workspace refreshed"})).toBeVisible();
  await page.getByRole("button", {name: "Compact view", exact: true}).click();
  await expect(page.locator(".shell")).toHaveAttribute("data-density", "compact");
  await page.reload();
  await expect(page.locator(".shell")).toHaveAttribute("data-density", "compact");
  await page.getByRole("button", {name: "Add website", exact: true}).click();
  await expect(page.getByRole("heading", {name: "Register a website"})).toBeVisible();
  expect(errors).toEqual([]);
});

test("phone layouts and workspace search stay usable without horizontal overflow", async ({page}) => {
  await page.setViewportSize({width: 390, height: 844});
  const connect = await workspace(page);
  await connect();
  await page.screenshot({path: "test-results/workspace-mobile.png", fullPage: true});
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.getByRole("button", {name: "Search workspace", exact: true}).click();
  await page.getByLabel("Find a page or action").fill("websites");
  await page.getByRole("dialog").getByRole("button", {name: /^Websites/}).click();
  await expect(page.getByRole("navigation").getByRole("button", {name: /^Websites/})).toBeInViewport();
  await page.getByRole("button", {name: "Add website", exact: true}).click();
  await expect(page.getByLabel("Website name", {exact: true})).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.screenshot({path: "test-results/workspace-mobile-form.png", fullPage: true});
  await page.getByRole("button", {name: "Disconnect", exact: true}).click();
  await expect(page.getByLabel("Workspace API key")).toBeVisible();
});
