import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { BrowserPreview, DecisionStatus, InteractionOutcome, PageChanges } from "./AgentPanel";

describe("agent task status and preview", () => {
  it("uses task completion when the final observation has no decision", () => {
    const html = renderToStaticMarkup(<DecisionStatus status="completed" verified />);
    expect(html).toContain("Completed");
    expect(html).toContain("Result verified");
    expect(html).not.toContain("Waiting for the worker");
  });

  it("reports a missing historical capture without showing a waiting state", () => {
    const html = renderToStaticMarkup(<BrowserPreview token="test" status="completed" />);
    expect(html).toContain("No browser capture was recorded for this run");
    expect(html).not.toContain("Waiting");
  });

  it("distinguishes in-place content changes from navigation", () => {
    const html = renderToStaticMarkup(<PageChanges url={false} content />);
    expect(html).toContain("URL unchanged");
    expect(html).toContain("Page content changed");
  });
});

describe("agent interaction outcomes", () => {
  it.each([undefined, null])("renders navigation recovery without scroll data (%s)", (scroll) => {
    const html = renderToStaticMarkup(<InteractionOutcome interaction={{
      changed: true,
      verified: true,
      verification: "Observed link navigated after a failed pointer trial",
      scroll,
    }} />);
    expect(html).toContain("verified");
    expect(html).toContain("Observed link navigated");
    expect(html).not.toContain("Scroll");
  });

  it.each([0, 125])("shows a recorded scroll position of %s", (y) => {
    const html = renderToStaticMarkup(<InteractionOutcome interaction={{
      changed: false, verified: false, verification: "No change", scroll: { y, height: 1000 },
    }} />);
    expect(html).toContain(`Scroll ${y}px`);
  });

  it("renders steps without interaction data", () => {
    expect(renderToStaticMarkup(<InteractionOutcome interaction={undefined} />)).toBe("");
  });
});
