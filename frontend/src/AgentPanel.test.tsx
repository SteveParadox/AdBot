import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { InteractionOutcome } from "./AgentPanel";

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
