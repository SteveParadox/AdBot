# Agent workflow robustness review

Reviewed on 2026-11-21. Scope: task admission, runner ownership, observation and action boundaries, recovery, durable tab state, verification, and publication of results.

## GitHub references

These are architecture references, not dependencies added to AdBot. Links refer to the default branches reviewed on the date above; upstream code can change.

| Project | Pattern reviewed | Application to AdBot |
| --- | --- | --- |
| [browser-use](https://github.com/browser-use/browser-use/blob/main/browser_use/agent/service.py) | `Agent.run` rejects concurrent use of one agent or browser and releases ownership in `finally`. | A SQL execution lease prevents duplicate dispatch of the same job token from launching another runner. Existing heartbeat and finalization renew and release that lease. |
| [agent-browser](https://github.com/vercel-labs/agent-browser/blob/main/README.md) | Observe, act, check the result; snapshot references expire after page changes. Covered or disabled targets fail explicitly. | Retain AdBot's observation-bound target validation and native actionability checks. Failed dispatched input is recorded as uncertain before any recovery observation and is never automatically replayed. |
| [Playwright MCP](https://github.com/microsoft/playwright-mcp) | Snapshot-based target references and explicit element, text, and value verification tools. | Keep action verification separate from issuing an action. Goal verification creates a candidate; publication requires successful checkpointing, runner cleanup, and worker finalization. |
| [Stagehand](https://github.com/browserbase/stagehand/blob/main/README.md) | Separate observation, native actions, schema-validated extraction, and cleanup. | Preserve AdBot's typed decisions and extraction schemas. Restore the active tab explicitly and detect closed/crashed pages before further interaction. |

## Concrete fixes

- **Duplicate runner ownership:** task claiming alone did not reject a second execution with the same valid token. `worker.py` now acquires an `execution:<job id>` lease before constructing a runner, using the existing atomic lease helper. A rejected duplicate neither finalizes the job nor releases the owner's leases.
- **Uncertain writes:** recovery observation previously preceded the durable ambiguity record. A dead page could therefore prevent that record. `agent/runner.py` now saves uncertainty and the sanitized underlying cause first, stops without recovery or cookie reads, and avoids even a fallible planning update on this path. Worker finalization also preserves uncertainty for unexpected exceptions or cancellation during an executing input action. Both browser and expired-worker recovery honor the marker even when the step is already marked failed.
- **Truthful completion:** verification previously persisted `AgentTask.result` before the final observation/checkpoint. `complete()` now only returns a candidate. The final step is marked successful after checkpointing. The worker atomically publishes the result, reusable memory, verification event, and completed job status after the runner returns successfully. Cancellation, checkpoint failure, cleanup failure, and return without verification publish no result.
- **Tab recovery:** map durable IDs to fresh browser-session IDs, restore each tab's purpose and bounded history, and select the previously active tab. If that tab falls outside the configured restore limit, select the first restored tab. Recovery restores URLs, not live DOM or unsaved form state.
- **Tab lifecycle:** detect renderer crashes, closed active pages and disconnected browsers; discard closed background tabs from the budget; restore the prior active tab and close a newly opened tab when its navigation fails. Do not silently switch from a lost active page to a different authenticated page.
- **Event-loop responsiveness:** remaining agent step reads/writes and final artifact validation now run as bounded synchronous transactions through `database_call`. Sessions are created and closed in the worker thread. No SQLAlchemy session crosses threads.
- **Failure reporting:** initialization and expired-lease failures retain structured diagnostics; interrupted mutations retain explicit uncertainty. Final logs use the actual persisted job status, including cancellation. The follow-up review corrected a false positive caused by finding the text `uncertain` inside the name of a false JSON flag. Cancelled in-flight input now also retains a manual-review diagnostic.
- **Navigation-response ownership:** navigation metadata belongs to its tab. A response from a background tab no longer overwrites the status used to record an active-tab interaction. The base runner also checks that its cached response belongs to the page being recorded.
- **Dialog ownership:** the initial agent page previously registered dismissal in both the base runner and the controller. Agent dialog handling now belongs to the controller, with one dismissal per event; dialog callbacks tolerate page/context closure. Crawl/workflow runners retain their own dismissal handler.

## Verification

`backend/tests/test_agent_robustness.py` exercises duplicate delivery, interrupted writes, tab restoration and lifecycle, independent HTTP statuses across tabs, page loss after dispatch, checkpoint/cleanup/cancellation after verification, missing verification, off-loop SQL with exactly one published result and reusable memory, true/false uncertainty flags, cancellation recovery guidance, and one dismissal per native dialog.

Existing agent, planning, export, API, concurrency and recovery tests cover normal operation and compatibility with these changes. Browser tests use real local Chromium, policy/proxy paths and a deterministic fixture model; they do not establish the quality of a live provider or compatibility with every external website. The focused review does not benchmark production database latency or claim exactly-once external form submission. SQL leases fence database ownership; an external website cannot participate in the SQL transaction, so uncertain submissions require manual inspection.

Final review validation:

- `python -m pytest tests/test_agent_robustness.py tests/test_agent.py tests/test_reliability_features.py tests/test_planning.py tests/test_planning_browser.py tests/test_browser.py tests/test_concurrency.py tests/test_concurrency_audit.py tests/test_api.py -k 'not other_engines' -q`: **121 passed, 1 skipped, 2 deselected**. The skipped case requires an explicitly configured isolated Redis; Firefox/WebKit agent cases were excluded. This run includes all 15 robustness regression cases and the dialog ownership fix.
- After the navigation-response ownership fix, the real-browser tab restoration, multi-tab/download agent flow, natural agent interactions, workflow and crawl cases passed **5/5** in 32.03 seconds.
- Changed Python files pass Ruff, compilation, UTF-8/null-byte inspection and `git diff --check`.
- The positive crawl-output test has an explicit 60-second test budget to allow browser startup and screenshots on a busy host. Deadline and timeout tests retain their own explicit limits.

Frontend colors and layout, browser identity/profile configuration, and the removed Phase 7 features are outside this change.
