import { test, expect } from "@playwright/test";
test("administrator saves custom user agent and duplicates reusable profile",async({page,request})=>{
 const key="e2e-local-key-000000000000000000000000";
 await page.goto("/");await page.getByLabel("Workspace API key").fill(key);
 await page.getByRole("button",{name:"Connect workspace"}).click();
 await page.getByRole("button",{name:"Content",exact:true}).click();
 await page.getByText("Identity settings and network diagnostics",{exact:true}).click();
 await expect(page.getByRole("heading",{name:"User-Agent management"})).toBeVisible();
 await page.getByLabel("Global User-Agent",{exact:true}).fill("Adbot-Compatibility-Test/7 (approved)");
 await page.getByRole("button",{name:"Duplicate profile"}).first().click();
 await page.getByRole("button",{name:"Save User-Agent settings"}).click();
 await expect(page.getByText("User-Agent configuration saved",{exact:true})).toBeVisible();
 const response=await request.get("/api/admin/user-agents",{headers:{Authorization:"Bearer "+key}});
 const config=await response.json();expect(config.global_value).toBe("Adbot-Compatibility-Test/7 (approved)");
 expect(config.profiles.length).toBe(2);
 await page.getByRole("button",{name:"Restore global default"}).click();
 await page.getByRole("button",{name:"Save User-Agent settings"}).click();
 await expect(page.getByLabel("Global User-Agent",{exact:true})).toHaveValue("");
});

test("weighted identity editor preserves partial JSON and comma-separated typing",async({page,request})=>{
 const key="e2e-local-key-000000000000000000000000";
 const headers={Authorization:"Bearer "+key};
 const initial=await (await request.get('/api/admin/user-agents',{headers})).json();
 try{
  await page.goto('/');await page.getByLabel('Workspace API key').fill(key);
  await page.getByRole('button',{name:'Connect workspace'}).click();
  await page.getByRole('button',{name:'Content',exact:true}).click();
  await page.getByText('Identity settings and network diagnostics',{exact:true}).click();
  const clients=page.getByLabel('Compatible clients (comma separated)').first();
  await clients.fill('chromium');await clients.press('End');await clients.pressSequentially(',firefox');
  await expect(clients).toHaveValue('chromium,firefox');
  await page.getByLabel('browser rotation',{exact:true}).selectOption('weighted');
  await page.getByLabel('Rotation profile IDs (comma separated)').fill('app-default');
  const weights=page.getByLabel('Profile weights JSON');
  await weights.fill('{');
  await expect(weights).toHaveValue('{');
  await page.getByRole('button',{name:'Save User-Agent settings'}).click();
  await expect(page.getByRole('alert')).toBeVisible();
  await weights.fill('{"app-default":');
  await weights.press('End');await weights.pressSequentially('3}');
  await expect(weights).toHaveValue('{"app-default":3}');
  await page.getByRole('button',{name:'Save User-Agent settings'}).click();
  await expect(page.getByText('User-Agent configuration saved',{exact:true})).toBeVisible();
  const saved=await (await request.get('/api/admin/user-agents',{headers})).json();
  expect(saved.services.browser.weights).toEqual({'app-default':3});
  expect(saved.profiles[0].clients).toEqual(['chromium','firefox']);
 }finally{
  const latest=await (await request.get('/api/admin/user-agents',{headers})).json();
  const restored=await request.post('/api/admin/user-agents',{headers,data:{revision:latest.revision,global_value:initial.global_value,profiles:initial.profiles,services:initial.services}});
  expect(restored.ok()).toBe(true);
 }
});
