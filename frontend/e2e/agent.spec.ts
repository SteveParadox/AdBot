import { test, expect } from "@playwright/test";

test("semantic form controls produce verified readable diagnostics", async ({page,request}) => {
  test.setTimeout(120000);
  const headers = { Authorization: "Bearer e2e-local-key-000000000000000000000000" };
  const response = await request.post("/api/websites", {headers,data:{name:"Semantic controls",base_url:"http://127.0.0.1:8765/agent/accessibility",allowed_domains:["127.0.0.1"],authorized:true,configuration:{max_pages:3,max_duration_seconds:120,screenshots:true}}});
  const site = await response.json();
  await page.goto("/");
  await page.getByLabel("Workspace API key").fill("e2e-local-key-000000000000000000000000");
  await page.getByRole("button",{name:"Connect workspace"}).click();
  await page.getByRole("button",{name:"AI Agent",exact:true}).click();
  await page.getByLabel("Agent target").selectOption(site.id);
  await page.getByLabel("Natural-language objective").fill("Search Backend Engineer jobs, enable remote only, then sort newest and cite the confirmation.");
  await page.getByLabel("Allow general form input").check();
  await page.getByRole("button",{name:"Start agent task"}).click();
  await expect(page.getByRole("heading",{name:"Verified task result"})).toBeVisible({timeout:60000});
  const diagnostics = page.getByRole("group", { name: "Semantic interaction diagnostics" });
  await expect(diagnostics.first()).toBeVisible();
  await expect(diagnostics.filter({hasText:"checkbox"}).first()).toContainText("Remote only");
  await expect(diagnostics.filter({hasText:"combobox"}).first()).toContainText("Sort results");
  await page.screenshot({path:"test-results/semantic-agent.png",fullPage:true});
});

test("preview preserves literal constraints and clears after form edits", async ({ page, request }) => {
  test.setTimeout(120000);
  const headers = { Authorization: "Bearer e2e-local-key-000000000000000000000000" };
  const response = await request.post("/api/websites", { headers, data: { name: "Planning preview", base_url: "http://127.0.0.1:8765/agent/news", allowed_domains: ["127.0.0.1"], authorized: true } });
  expect(response.ok()).toBeTruthy();
  const site = await response.json();
  await page.goto("/");
  await page.getByLabel("Workspace API key").fill("e2e-local-key-000000000000000000000000");
  await page.getByRole("button", { name: "Connect workspace" }).click();
  await page.getByRole("button", { name: "AI Agent", exact: true }).click();
  await page.getByLabel("Agent target").selectOption(site.id);
  await page.getByLabel("Natural-language objective").fill("Find Orion AI launch dates then export CSV, exclude weather.");
  await page.getByRole("button", { name: "Preview task understanding" }).click();
  const plan = page.getByRole("region", { name: "Task plan" });
  await expect(plan).toBeVisible();
  await plan.getByText("Original requirements and interpretation", { exact: true }).click();
  await expect(plan.getByText("Explicit constraints: exclude weather", { exact: true })).toBeVisible();
  await expect(plan.getByText("Export requires a configured, owned extraction dataset. Read-only research may continue.", { exact: true })).toBeVisible();
  await page.getByLabel("Natural-language objective").fill("Find Orion AI launch dates.");
  await expect(plan).toHaveCount(0);
});

test("natural-language objective uses observed links and returns cited evidence", async ({
  page,
}) => {
  test.setTimeout(120000);
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
  const plan = page.getByRole("region", { name: "Task plan" });
  await expect(plan.getByRole("heading", { name: "Task understanding and plan" })).toBeVisible();
  await expect(plan.getByText("Verified completion", { exact: true })).toBeVisible();
  await expect(
    page.getByText("Fixture verifier found quoted source evidence", {
      exact: true,
    }),
  ).toBeVisible();
  await page.getByText("Interaction trace · automated session", { exact: true }).first().click();
  await expect(page.getByRole("columnheader", { name: "Started (UTC)" }).first()).toBeVisible();
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
