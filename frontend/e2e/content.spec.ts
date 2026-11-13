import { test, expect } from "@playwright/test";
const key = "e2e-local-key-000000000000000000000000";
test("administrator publishes content and public login refreshes", async ({page,request}) => {
  await page.goto("/");
  await page.getByLabel("Workspace API key").fill(key);
  await page.getByRole("button",{name:"Connect workspace"}).click();
  await page.getByRole("button",{name:"Content",exact:true}).click();
  await page.getByLabel("Section key").fill("announcement");
  await page.getByLabel("title",{exact:true}).fill("Published announcement");
  await page.getByLabel("description",{exact:true}).fill("<script>window.injected=true</script>");
  await page.getByRole("combobox",{name:"Status",exact:true}).selectOption("draft");
  await page.getByRole("button",{name:"Save",exact:true}).click();
  await expect(page.getByRole("status")).toHaveText("Saved");
  let response = await request.get("/api/content");
  expect(await response.text()).not.toContain("Published announcement");
  await page.getByRole("combobox",{name:"Status",exact:true}).selectOption("published");
  await page.getByRole("button",{name:"Save",exact:true}).click();
  await expect(page.getByRole("status")).toHaveText("Saved");
  await page.getByRole("button",{name:"Disconnect",exact:true}).click();
  await expect(page.getByRole("heading",{name:"Published announcement"})).toBeVisible();
  expect(await page.evaluate(()=>Boolean((window as Window & {injected?:boolean}).injected))).toBe(false);
  await page.setViewportSize({width:375,height:812});
  await expect(page.getByRole("heading",{name:"Published announcement"})).toBeVisible();
  await request.delete("/api/admin/content/announcement",{headers:{Authorization:"Bearer "+key}});
});

test("dynamic metadata and backend failure retain readable fallback", async ({page,request}) => {
  const headers = {Authorization:"Bearer "+key};
  const original = (await (await request.get("/api/admin/content",{headers})).json()).items.find((s:{key:string})=>s.key==="seo");
  try {
    await request.post("/api/admin/content/seo",{headers,data:{status:"published",position:original.position,draft:{title:"Dynamic SEO",description:"Published description",canonical:"https://example.com/"}}});
    await page.goto("/");
    await expect(page).toHaveTitle("Dynamic SEO");
    await expect(page.locator('meta[property="og:title"]')).toHaveAttribute("content","Dynamic SEO");
    await expect(page.locator('link[rel="canonical"]')).toHaveAttribute("href","https://example.com/");
  } finally {
    await request.post("/api/admin/content/seo",{headers,data:{status:original.status,position:original.position,draft:original.draft}});
  }
  await page.route("**/api/content",route=>route.fulfill({status:503,contentType:"application/json",body:JSON.stringify({detail:"Unavailable"})}));
  await page.reload();
  await expect(page.getByRole("alert")).toContainText("Website content is temporarily unavailable");
  await expect(page.getByRole("heading",{name:"Your web, in focus."})).toBeVisible();
});
