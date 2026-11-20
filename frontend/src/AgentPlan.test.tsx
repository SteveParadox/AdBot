import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import { AgentPlan, type Planning } from "./AgentPlan";

it("renders actual progress, constraints and recovery without treating checkpoints as final success", () => {
  const planning: Planning = {
    specification: { objective: "Find articles <script>bad()</script>", instruction_clauses: ["Find articles"], constraints: ["Never submit"], success_criteria: ["Cited answer"], output_format: "answer", ambiguities: [] },
    plan: { intent: { entities: [], secondary_objectives: [], optional_outcomes: [], ambiguities: [] }, subtasks: [{ id: "collect", description: "Collect evidence", kind: "collect", dependencies: ["research"], status: "blocked", attempts: 2, step_budget: 10, outcome: "Permission required" }] },
    generation: 2, active_subtask: "collect", warnings: ["No artifact requested"], replans: [{ generation: 2, reason: "Target changed", classification: "requires_replanning", subtask_id: "collect", url: "https://example.org" }],
  };
  const html = renderToStaticMarkup(<AgentPlan planning={planning} />);
  for (const text of ["Never submit", "blocked", "Target changed", "requires_replanning", "Final completion requires separate evidence verification", "2/10"]) expect(html).toContain(text);
  expect(html).not.toContain("<script>");
  expect(html).toContain("&lt;script&gt;");
});

it("displays pending planning state", () => {
  expect(renderToStaticMarkup(<AgentPlan />)).toContain("Waiting for a saved plan.");
});
