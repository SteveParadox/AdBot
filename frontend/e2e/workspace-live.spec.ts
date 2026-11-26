import { test, expect } from "@playwright/test";

test("all workspace pages stay responsive against the real API", async ({page, request}) => {
  test.setTimeout(120000);
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  const response = await request.post("/api/websites", {headers:{Authorization:"Bearer e2e-local-key-000000000000000000000000"}, data:{name:"Responsive fixture",base_url:"http://127.0.0.1:8765/",allowed_domains:["127.0.0.1"],authorized:true}});
  expect(response.ok()).toBeTruthy();
  await page.goto("/");
  await page.getByLabel("Workspace API key").fill("e2e-local-key-000000000000000000000000");
  await page.getByRole("button", {name:"Connect workspace"}).click();
  await expect(page.getByRole("heading", {name:"A clearer view of your web."})).toBeVisible();
  await expect(page.getByText("API connected", {exact:true})).toBeVisible();
  await expect(page.locator(".shell > aside")).toHaveCSS("background-color", "rgb(255, 255, 255)");
  await expect(page.locator("html")).toHaveCSS("background-color", "rgb(246, 247, 251)");
  await expect(page.locator("h1")).toHaveCSS("font-weight", "500");

  for (const width of [1440, 390]) {
    await page.setViewportSize({width, height:900});
    for (const section of ["Overview", "Websites", "Jobs", "AI Agent", "Data Extraction", "Workflows", "Schedules", "Content", "Automation"]) {
      const navigation = page.getByRole("navigation", {name:"Workspace navigation"});
      const button = navigation.getByRole("button", {name:new RegExp(`^${section}(?: [0-9]+)?$`)});
      await button.click();
      await expect(button).toHaveAttribute("aria-current", "page");
      await expect(page.getByRole("main").getByText(`${section} workspace`, {exact:true})).toBeAttached();
      if (section === "AI Agent") {
        await expect(page.getByLabel("Natural-language objective", {exact:true})).toBeVisible();
        await expect(page.getByLabel("Agent priority (-10 to 10)", {exact:true})).not.toBeVisible();
        await page.getByText("Dataset output, priority and dependencies", {exact:true}).click();
        await expect(page.getByLabel("Agent priority (-10 to 10)", {exact:true})).toBeVisible();
        await page.getByText("Dataset output, priority and dependencies", {exact:true}).click();
      }
      if (section === "Automation") {
        const surface = page.locator(".automation-admin");
        await expect(surface.getByRole("heading", {name:"Automation Control Center"})).toBeVisible();
        async function checkSpacing(buttons: import("@playwright/test").Locator) {
          const count = await buttons.count();
          expect(count).toBeGreaterThan(1);
          for (let index = 1; index < count; index++) {
            const first = await buttons.nth(index - 1).boundingBox();
            const next = await buttons.nth(index).boundingBox();
            expect(first && next).toBeTruthy();
            const gap = Math.abs(first!.y - next!.y) < 2 ? next!.x - first!.x - first!.width : next!.y - first!.y - first!.height;
            expect(gap).toBeGreaterThanOrEqual(15);
          }
        }
        await checkSpacing(surface.locator(":scope > .automation-actions > button"));
        await surface.getByText("Advanced policy editor & approved configurations", {exact:true}).click();
        await checkSpacing(surface.locator(".admin-disclosure .automation-actions > button"));
        await page.evaluate(() => window.scrollTo({top:0, left:0, behavior:"instant"}));
        await page.screenshot({path:`test-results/automation-button-spacing-${width}.png`,fullPage:true});
        await surface.getByText("Advanced policy editor & approved configurations", {exact:true}).click();
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), `${section} at ${width}px overflows`).toBeTruthy();
      if (["Overview", "AI Agent", "Data Extraction", "Automation"].includes(section)) {
        await page.evaluate(() => window.scrollTo({top:0, left:0, behavior:"instant"}));
        await page.screenshot({path:`test-results/live-${section.replaceAll(" ","-")}-${width}.png`,fullPage:true});
      }
    }
  }
  expect(errors).toEqual([]);
});
