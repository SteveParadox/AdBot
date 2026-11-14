import { test, expect } from "@playwright/test";
test("administrator saves custom user agent and duplicates reusable profile",async({page,request})=>{
 const key="e2e-local-key-000000000000000000000000";
 await page.goto("/");await page.getByLabel("Workspace API key").fill(key);
 await page.getByRole("button",{name:"Connect workspace"}).click();
 await page.getByRole("button",{name:"Content",exact:true}).click();
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
