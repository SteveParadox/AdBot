export type SemanticAction = {
  role: string; name: string; strategy: string; element_id: string; actionable: boolean;
  context?: { name?: string; heading?: string } | null;
};
type Focus = { tag?: string; id?: string; role?: string; name?: string };
export type SemanticInteraction = {
  key?: string | null; focus_before?: Focus; focus_after?: Focus; verified: boolean; verification: string;
  focus_recovery?: string | null;
  dialogs?: { focus_contained: boolean; focus_restored: (boolean | null)[] };
};

type Resolution = { role?: string; name?: string; accessible_name?: string; strategy?: string; element_id?: string; actionable?: boolean; status?: string };
export function SemanticTrace({ semantic: completed, interaction, resolution }: { semantic?: SemanticAction; interaction?: SemanticInteraction; resolution?: Resolution }) {
  const semantic = completed || (resolution?.role ? { role: resolution.role, name: resolution.accessible_name || resolution.name || "", strategy: resolution.strategy || "Unresolved", element_id: resolution.element_id || "", actionable: resolution.actionable === true, context: null } : undefined);
  if (!semantic && !interaction?.focus_after) return null;
  const focusName = (focus?: Focus) => focus ? [focus.name || focus.role || focus.tag, focus.id && `#${focus.id}`].filter(Boolean).join(" ") || "Document" : "Unknown";
  return <div className="semantic-trace" role="group" aria-label="Semantic interaction diagnostics">
    {semantic && <>
      <p className="hint"><strong>{semantic.role}</strong>{semantic.name ? `: ${semantic.name}` : " (unlabelled control)"}</p>
      <p className="hint">Locator: {semantic.strategy} · {semantic.actionable ? "Actionable at resolution" : "Actionability not established"}</p>
      {(semantic.context?.name || semantic.context?.heading) && <p className="hint">Context: {semantic.context.name || semantic.context.heading}</p>}
    </>}
    {interaction?.key && <p className="hint">Native key: {interaction.key}</p>}
    {resolution?.status === "failed" && <p className="hint">Element resolution failed; fresh observation required.</p>}
    {interaction?.focus_after && <p className="hint">Focus: {focusName(interaction.focus_before)} → {focusName(interaction.focus_after)}</p>}
    {interaction?.focus_recovery && <p className="hint">{interaction.focus_recovery}</p>}
    {!!interaction?.dialogs?.focus_restored.length && <p className="hint">Dialog focus restoration: {interaction.dialogs.focus_restored.map(v => v === null ? "opener unknown" : v ? "confirmed" : "not confirmed").join(", ")}</p>}
  </div>;
}

export type SemanticObservationData = { observation_metrics?: { candidates: number; included: number; truncated: boolean; characters: number; duration_ms: number }; elements?: { element_id: string; role: string; name: string; actionable?: boolean; locator_strategy?: string; invalid?: boolean; readonly?: boolean }[] };
export function SemanticObservation({ observation }: { observation?: SemanticObservationData }) {
  const metrics = observation?.observation_metrics;
  if (!metrics) return null;
  return <details><summary>Recognized semantic controls · {metrics.included}/{metrics.candidates}</summary>
    <p className="hint">{metrics.characters.toLocaleString()} observation characters · {Math.round(metrics.duration_ms)}ms · {metrics.truncated ? "Truncated; relevant controls prioritized" : "Within observation limit"}</p>
    <div className="table-wrap"><table><thead><tr><th scope="col">Control</th><th scope="col">State</th><th scope="col">Locator</th></tr></thead>
      <tbody>{observation.elements?.map(e => <tr key={e.element_id}><td>{e.role}: {e.name || "Unlabelled"}</td><td>{e.actionable ? "Available" : "Blocked"}{e.invalid ? " · Invalid" : ""}{e.readonly ? " · Read only" : ""}</td><td>{e.locator_strategy}</td></tr>)}</tbody>
    </table></div>
  </details>;
}
