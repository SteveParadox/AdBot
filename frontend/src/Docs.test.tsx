import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import Docs from "./Docs";
import { docs, findDoc, matchDocsPath } from "./docsContent";

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
