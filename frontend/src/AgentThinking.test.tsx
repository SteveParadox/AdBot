import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { AgentThinking } from "./AgentPanel";

describe("AgentThinking", () => {
  it("shows an accessible animated indicator while running", () => {
    const html = renderToStaticMarkup(<AgentThinking status="running" />);
    expect(html).toContain("Thinking…");
    expect(html).toContain('role="status"');
    expect(html).toContain('class="lucide lucide-loader-circle spin"');
  });

  it.each(["queued", "paused", "completed", "failed", "cancelled", "waiting_for_review"])("hides for %s", (status) => {
    expect(renderToStaticMarkup(<AgentThinking status={status} />)).toBe("");
  });
});
