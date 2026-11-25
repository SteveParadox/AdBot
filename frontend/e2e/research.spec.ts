import { expect, test } from "@playwright/test";

const id = "a17424af-60ba-468c-8820-bcbed878d348";
const conversation = "8a94b136-1cd3-4612-ad1f-48aaa4dfa8ef";
const root = "/api/research/v1";
const question = "What's new in quantum error correction?";
const source = { id: "study", url: "https://example.com/study", title: "Quantum processor study", domain: "example.com",
  published_at: "2026-10-01", retrieved_at: 1770000000, content_hash: "fixture", query: "quantum" };
const task = {
  id, conversation_id: conversation, status: "queued", mode: "quick",
  question: { question, mode: "quick" }, error: null, result: {},
};

test("researches without a website and displays citations and evidence on mobile", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.addInitScript(() => sessionStorage.setItem("adbot-token", "fixture-workspace-token"));
  let submitted = false, connected = false;
  await page.route(`**${root}/**`, async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === `${root}/providers`) return route.fulfill({json: {enabled: true, model_configured: true, providers: [{name: "searxng"}]}});
    if (path === `${root}/conversations`) return route.fulfill({json: {items: submitted ? [{id: conversation, title: question}] : [], total: Number(submitted)}});
    if (path === `${root}/query`) {
      expect(route.request().postDataJSON()).toEqual({question, mode: "quick", conversation_id: null, country: null, freshness: null});
      expect(route.request().headers()["idempotency-key"]).toBeTruthy();
      submitted = true;
      return route.fulfill({status: 202, json: task});
    }
    if (path.endsWith("/events")) {
      if (!connected) {connected = true; return route.abort();}
      const events = ["searching", "retrieving", "completed"].map((event_type, i) =>
        `id: ${i + 1}\nevent: progress\ndata: ${JSON.stringify({id: i + 1, event_type, message: event_type, details: {}, timestamp: 1})}\n\n`).join("");
      return route.fulfill({contentType: "text/event-stream", body: events});
    }
    if (path.endsWith("/evidence")) {
      const offset = new URL(route.request().url()).searchParams.get("offset");
      const first = offset === "0";
      return route.fulfill({json: {
        items: [{id: first ? "quote-1" : "quote-2", source_id: "study", retrieved_at: 1770000000,
          quote: first ? "A quantum processor detected and corrected errors." : "A second passage describes the study protocol.",
          location: first ? "normalized-text:block-1" : "normalized-text:block-2"}],
        total: 2,
      }});
    }
    if (path.endsWith(id)) return route.fulfill({json: {
      ...task, status: "completed", result: {quality: "complete", answer: "Quantum processors can correct errors. [1](https://example.com/study)", sources: [source]},
    }});
    return route.fulfill({status: 404, json: {detail: "Unexpected fixture path"}});
  });
  await page.goto("/research");
  await expect(page.getByRole("heading", {name: "Web Research"})).toBeVisible();
  await page.getByLabel("Question").fill(question);
  await page.getByLabel("Mode").selectOption("quick");
  await page.getByRole("button", {name: "Send"}).click();
  await expect(page.getByText("Quantum processors can correct errors.")).toBeVisible();
  await expect(page.getByRole("link", {name: "1", exact: true})).toHaveAttribute("href", source.url);
  await page.getByText("Sources and evidence (1)").click();
  await expect(page.getByText("A quantum processor detected and corrected errors.")).toBeVisible();
  await expect(page.getByText("A second passage describes the study protocol.")).toBeVisible();
  await expect(page.getByRole("link", {name: source.title})).toHaveAttribute("rel", "noreferrer noopener");
  await expect(page.getByLabel("Question")).toHaveAttribute("placeholder", "Ask a follow-up question");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("keeps the website agent available from the research mode selector", async ({page}) => {
  await page.addInitScript(() => sessionStorage.setItem("adbot-token", "fixture-workspace-token"));
  await page.route(`**${root}/conversations`, route => route.fulfill({json: {items: [], total: 0}}));
  await page.route(`**${root}/providers`, route => route.fulfill({json: {enabled: true, model_configured: true, providers: []}}));
  await page.goto("/research");
  await page.getByLabel("Mode").selectOption("website_agent");
  await expect(page.getByRole("link", {name: "Open Website Agent"})).toHaveAttribute("href", "/?tab=agent");
});
