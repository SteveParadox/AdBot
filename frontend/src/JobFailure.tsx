import type { Job } from "./api";

export function JobFailure({ failure }: { failure: Job["failure"] }) {
  if (!failure) return null;
  return <div role="status" aria-label="Job failure diagnostics">
    <p>Failure: {failure.category.replaceAll("_", " ")} - Stage: {failure.stage.replaceAll("_", " ")}</p>
    <p>Last successful action: {failure.last_successful_action?.action || "None recorded"}</p>
    <p>{failure.automatic_retry_scheduled ? "Automatic retry queued" : failure.retry_eligible ? "Retry may be attempted after resolving the cause" : "Review required before another attempt"}</p>
    <p>{failure.suggested_recovery}</p>
  </div>;
}
