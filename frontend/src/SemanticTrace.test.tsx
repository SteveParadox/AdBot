import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import { SemanticTrace } from "./SemanticTrace";

it("shows observed semantic strategy and focus without including form values", () => {
  const html = renderToStaticMarkup(<SemanticTrace semantic={{ role: "checkbox", name: "Remote <script>only</script>", strategy: "associated label", element_id: "e1", actionable: true }} interaction={{ key: "Space", verified: true, verification: "checked state", focus_before: { tag: "BODY" }, focus_after: { role: "checkbox", id: "remote" } }} />);
  for (const text of ["checkbox", "associated label", "Native key: Space", "#remote", "Actionable at resolution"]) expect(html).toContain(text);
  expect(html).not.toContain("<script>");
});
it("keeps legacy outcomes without semantic data renderable", () => {
  expect(renderToStaticMarkup(<SemanticTrace />)).toBe("");
});
