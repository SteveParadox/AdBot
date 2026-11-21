export type Planning = {
  specification: { dataset_query?: unknown; objective: string; instruction_clauses: string[]; constraints: string[]; success_criteria: string[]; output_format: string; ambiguities: { detail: string; category: string }[] };
  plan: { intent: { secondary_objectives: string[]; entities: string[]; optional_outcomes: string[]; ambiguities: { detail: string; category: string }[] }; subtasks: { id: string; description: string; kind: string; dependencies: string[]; status: string; attempts: number; step_budget: number; outcome: string }[] };
  active_subtask: string | null;
  generation: number;
  warnings: string[];
  replans: { generation: number; reason: string; classification: string; subtask_id: string | null; url: string }[];
};

export function AgentPlan({ planning }: { planning?: Planning | null }) {
  return <section className="panel form-panel" aria-label="Task plan">
    <h2>Task understanding and plan</h2>
    {!planning ? <p>Waiting for a saved plan.</p> : <>
      <p>{planning.specification.objective}</p>
      {planning.specification.dataset_query != null && <p className="hint">Dataset selection: {JSON.stringify(planning.specification.dataset_query)}</p>}
      <p className="hint">Output: {planning.specification.output_format} · Active: {planning.active_subtask || "None"} · Plan version {planning.generation}</p>
      <p className="hint">Checkpoints record observed progress. Final completion requires separate evidence verification.</p>
      <details><summary>Original requirements and interpretation</summary>
        <ul>{planning.specification.instruction_clauses.map((value, i) => <li key={i}>{value}</li>)}</ul>
        <p>Explicit constraints: {planning.specification.constraints.join("; ") || "None supplied"}</p>
        <p>Success criteria: {planning.specification.success_criteria.join("; ") || "Original objective"}</p>
        <p>Entities: {planning.plan.intent.entities.join(", ") || "No additional entities inferred"}</p>
        <p>Secondary outcomes: {planning.plan.intent.secondary_objectives.join("; ") || "None"}</p>
        <p>Optional outcomes: {planning.plan.intent.optional_outcomes.join("; ") || "None"}</p>
      </details>
      {[...planning.specification.ambiguities, ...planning.plan.intent.ambiguities].map((a, i) => <p className="hint" key={i}>{a.category}: {a.detail}</p>)}
      {planning.warnings.map((warning, i) => <p role="status" key={i}>{warning}</p>)}
      <ol>{planning.plan.subtasks.map(node => <li key={node.id}>
        <strong>{node.description}</strong> — {node.status}{node.id === planning.active_subtask ? " (current)" : ""}
        <p className="hint">{node.id} · Depends on: {node.dependencies.join(", ") || "None"} · Actions {node.attempts}/{node.step_budget}</p>
        {node.outcome && <p className="hint">{node.outcome}</p>}
      </li>)}</ol>
      {!!planning.replans.length && <details open><summary>Replanning history</summary><ol>{planning.replans.map(r => <li key={r.generation}>
        Version {r.generation} · {r.subtask_id || "Task"} · {r.classification}: {r.reason}
      </li>)}</ol></details>}
    </>}
  </section>;
}
