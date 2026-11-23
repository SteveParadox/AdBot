import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import Docs from "./Docs";
import { docs, findDoc, matchDocsPath, searchDocs } from "./docsContent";

describe("user documentation routes", () => {
  it("matches only the documentation path boundary", () => {
    expect(matchDocsPath("/docs")).toBe(true);
    expect(matchDocsPath("/docs/jobs")).toBe(true);
    expect(matchDocsPath("/docstring")).toBe(false);
    expect(matchDocsPath("/")).toBe(false);
    expect(findDoc("/docs/")?.slug).toBe("introduction");
    expect(findDoc("/docs/jobs/")?.slug).toBe("jobs");
  });
  it("renders every guide without workspace authentication or API queries", () => {
    expect(new Set(docs.map(page => page.slug)).size).toBe(docs.length);
    for (const page of docs) {
      const html = renderToStaticMarkup(<Docs path={`/docs/${page.slug}`}/>);
      expect(html).toContain(`<h1>${page.title}</h1>`);
      expect(html).toContain('aria-current="page"');
      expect(html).toContain('aria-label="Documentation navigation"');
      expect(html).toContain('Search documentation</span>');
      for (const section of page.sections) {
        expect(html).toContain(`href="#${section.id}"`);
        expect(html).toContain(`id="${section.id}"`);
      }
    }
  });
  it("offers recovery for unknown guides", () => {
    const html = renderToStaticMarkup(<Docs path="/docs/missing"/>);
    expect(html).toContain("Guide not found");
    expect(html).toContain('href="/docs"');
    expect(html).not.toContain('aria-current="page"');
  });
});

it("rejects lookalike and malformed paths rather than resolving a guide", () => {
  for (const path of ["/jobs", "/docsjobs", "/docs//", "/docs/jobs/extra", "/docs/../jobs", "/docs/%3Cscript%3E"]) {
    expect(findDoc(path)).toBeUndefined();
  }
});

it("resolves every internal guide link and section anchor", () => {
  for (const page of docs) {
    const html = renderToStaticMarkup(<Docs path={`/docs/${page.slug}`}/>);
    const ids = [...html.matchAll(/ id="([^"]+)"/g)].map(match => match[1]);
    expect(new Set(ids).size).toBe(ids.length);
    for (const [, href] of html.matchAll(/href="([^"]+)"/g)) {
      if (href.startsWith("/docs")) expect(findDoc(href), href).toBeDefined();
      if (href.startsWith("#")) expect(ids).toContain(href.slice(1));
      expect(href).not.toMatch(/^(javascript|data):/);
    }
  }
});

it("searches guide bodies and steps with trimming and case folding", () => {
  expect(searchDocs("  ENCRYPTED browser session  ").map(page => page.slug)).toContain("ai-agent");
  expect(searchDocs("Link-discovery crawl").map(page => page.slug)).toContain("quick-start");
  expect(searchDocs("no-guide-matches-this-phrase")).toEqual([]);
  expect(searchDocs("   ")).toEqual(docs);
});
