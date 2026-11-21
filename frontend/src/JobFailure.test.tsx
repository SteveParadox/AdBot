import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import { JobFailure } from "./JobFailure";

it("shows uncertainty and recovery without offering an automatic retry", () => {
  const html = renderToStaticMarkup(<JobFailure failure={{category:"uncertain_submission",stage:"interaction",last_successful_action:{action:"NAVIGATE",step:1},retry_eligible:false,automatic_retry_scheduled:false,suggested_recovery:"Inspect destination before another task"}}/>);
  expect(html).toContain("uncertain submission");
  expect(html).toContain("NAVIGATE");
  expect(html).toContain("Review required");
  expect(html).not.toContain("Automatic retry queued");
});

it("renders nothing for a job without a diagnostic", () => {
  expect(renderToStaticMarkup(<JobFailure failure={null}/>)).toBe("");
});
