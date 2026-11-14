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
  await page.getByRole("button",{name:"New section",exact:true}).click();
  await expect(page.getByLabel("Section key")).toHaveValue("");
  await expect(page.getByLabel("title",{exact:true})).toHaveValue("");
  await page.getByRole("combobox",{name:"Select section",exact:true}).selectOption("announcement");
  await expect(page.getByLabel("title",{exact:true})).toHaveValue("Published announcement");

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
  const current=await (await request.get("/api/admin/content/announcement",{headers:{Authorization:"Bearer "+key}})).json();
  await request.delete("/api/admin/content/announcement",{headers:{Authorization:"Bearer "+key,"If-Match":current.revision}});
});

test("dynamic metadata and backend failure retain readable fallback", async ({page,request}) => {
  const headers = {Authorization:"Bearer "+key};
  const original = (await (await request.get("/api/admin/content",{headers})).json()).items.find((s:{key:string})=>s.key==="seo");
  try {
    await request.post("/api/admin/content/seo",{headers,data:{revision:original.revision,status:"published",position:original.position,draft:{title:"Dynamic SEO",description:"Published description",canonical:"https://example.com/"}}});
    await page.goto("/");
    await expect(page).toHaveTitle("Dynamic SEO");
    await expect(page.locator('meta[property="og:title"]')).toHaveAttribute("content","Dynamic SEO");
    await expect(page.locator('link[rel="canonical"]')).toHaveAttribute("href","https://example.com/");
  } finally {
    const latest=await (await request.get("/api/admin/content/seo",{headers})).json();
    await request.post("/api/admin/content/seo",{headers,data:{revision:latest.revision,status:original.status,position:original.position,draft:original.draft}});
  }
  await page.route("**/api/content",route=>route.fulfill({status:503,contentType:"application/json",body:JSON.stringify({detail:"Unavailable"})}));
  await page.reload();
  await expect(page.getByRole("alert")).toContainText("Website content is temporarily unavailable");
  await expect(page.getByRole("heading",{name:"Your web, in focus."})).toBeVisible();
});

test("stale content save preserves draft and supports explicit merge",async({page,request})=>{
  const headers={Authorization:"Bearer e2e-local-key-000000000000000000000000"};
  const path="/api/admin/content/conflict-demo";
  const original=await (await request.post(path,{headers,data:{draft:{title:"Original"}}})).json();
  await page.goto("/");
  await page.getByLabel("Workspace API key").fill("e2e-local-key-000000000000000000000000");
  await page.getByRole("button",{name:"Connect workspace"}).click();
  await page.getByRole("button",{name:"Content",exact:true}).click();
  await page.getByRole("combobox",{name:"Select section",exact:true}).selectOption("conflict-demo");
  await page.getByLabel("title",{exact:true}).fill("My unsaved work");
  const other=await request.post(path,{headers,data:{revision:original.revision,draft:{title:"Other administrator"}}});
  expect(other.ok()).toBe(true);
  await page.getByRole("button",{name:"Save",exact:true}).click();
  await expect(page.getByRole("alert")).toContainText("Section changed");
  await expect(page.getByLabel("title",{exact:true})).toHaveValue("My unsaved work");
  await expect(page.getByRole("heading",{name:"Other administrator",exact:true})).toBeVisible();
  await expect(page.getByRole("button",{name:"Save",exact:true})).toBeDisabled();
  await page.getByRole("button",{name:"Keep my draft for manual merge"}).click();
  await page.getByLabel("title",{exact:true}).fill("Merged content");
  await page.getByRole("button",{name:"Save",exact:true}).click();
  await expect(page.getByRole("status")).toHaveText("Saved");
  const final=await (await request.get(path,{headers})).json();
  expect(final.draft.title).toBe("Merged content");
  await request.delete(path,{headers:{...headers,"If-Match":final.revision}});
});
