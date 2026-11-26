import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { AgentTaskActivity } from "./AgentPanel";

describe("AgentTaskActivity", () => {
  it.each([
    [undefined, "Loading agent task…"],
    ["running", "Thinking…"],
  ])("renders the activity for %s with a decorative spinner", (status, label) => {
    const html = renderToStaticMarkup(<AgentTaskActivity status={status} />);
    expect(html).toContain(label);
    expect(html).toContain('role="status"');
    expect(html).toMatch(/<svg[^>]*class="[^"]*\bspin\b[^"]*"[^>]*aria-hidden="true"/);
  });

  it.each(["queued", "paused", "waiting_user", "completed", "failed", "cancelled"])(
    "keeps the status region empty for %s",
    (status) => {
      const html = renderToStaticMarkup(<AgentTaskActivity status={status} />);
      expect(html).toMatch(/<p[^>]*role="status"><\/p>/);
    },
  );
});
