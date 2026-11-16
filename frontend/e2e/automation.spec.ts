import { test, expect } from "@playwright/test";
const headers = { Authorization: "Bearer e2e-local-key-000000000000000000000000" };

test("automation preserves conflicting drafts and runs manually released jobs", async ({ page, request }) => {
  const path = "/api/admin/automation";
  const initial = await (await request.get(path, { headers })).json();
  async function configure(changes: Record<string, unknown>) {
    const current = await (await request.get(path, { headers })).json();
    const response = await request.post(path, { headers, data: { revision: current.revision, policy: { ...current.policy, ...changes } } });
    expect(response.ok()).toBe(true);
  }
  let website: string | undefined;
  try {
    await page.goto("/");
    await page.getByLabel("Workspace API key").fill("e2e-local-key-000000000000000000000000");
    await page.getByRole("button", { name: "Connect workspace" }).click();
    await page.getByRole("button", { name: "Automation", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Automation Control Center" })).toBeVisible();
    await page.getByText("Advanced policy editor & approved configurations", { exact: true }).click();
    const editor = page.getByLabel("Automation policy JSON");
    await editor.fill(JSON.stringify({ ...initial.policy, max_backlog: 1004 }));
    await configure({ max_backlog: 1003 });
    await page.getByRole("button", { name: "Save automation policy", exact: true }).click();
    await expect(page.getByText("Control policy changed; reload", { exact: true })).toBeVisible();
    expect(JSON.parse(await editor.inputValue()).max_backlog).toBe(1004);
    const stored = await (await request.get(path, { headers })).json();
    expect(stored.policy.max_backlog).toBe(1003);
    await page.getByRole("button", { name: "Discard draft and reload current policy" }).click();
    await configure({ enabled: false, paused: false });
    const site = await request.post("/api/websites", { headers, data: {
      name: "Automation fixture", base_url: "http://127.0.0.1:8765/", allowed_domains: ["127.0.0.1"], authorized: true,
      configuration: { max_pages: 1, max_depth: 0, delay_seconds: 0.1, max_duration_seconds: 20, screenshots: false },
    } });
    expect(site.ok()).toBe(true);
    website = (await site.json()).id;
    const queued = await (await request.post("/api/jobs", { headers, data: { website_id: website } })).json();
    await page.reload();
    await page.getByRole("button", { name: "Automation", exact: true }).click();
    await expect(page.getByText(/live workers/)).toContainText("live workers");
    const row = page.getByRole("listitem").filter({ hasText: queued.id });
    await row.getByRole("button", { name: "Release job" }).click();
    await expect.poll(async () => (await (await request.get(`/api/jobs/${queued.id}`, { headers })).json()).status,
      { timeout: 40000 }).toBe("completed");
    const next = await (await request.post("/api/jobs", { headers, data: { website_id: website } })).json();
    await page.getByRole("button", { name: "Emergency stop all jobs" }).click();
    await expect.poll(async () => (await (await request.get(`/api/jobs/${next.id}`, { headers })).json()).status).toBe("cancelled");
  } finally {
    await configure(initial.policy);
    if (website) await request.delete(`/api/websites/${website}`, { headers });
  }
});
