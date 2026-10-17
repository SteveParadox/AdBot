# Context-aware interaction engine

The goal-driven planner selects actions from the current semantic observation and task history. `backend/app/agent/interaction.py` executes deterministic Playwright input and records observable outcomes. It does not add random delays, cursor paths, fabricated engagement, or stealth behavior.

## Actions and outcomes

- `HOVER`, `FOCUS`, `CLICK`: latest observed element ID; native Playwright hover/focus/click. Pointer actions first run Playwright's trial actionability check (visible, stable, enabled and receiving pointer events). Disabled and covered targets fail and trigger replanning. The controller checks live field type, href and form destination against the observation before input.
- `TYPE`: native fill by default; `input_method: "keyboard"` uses `press_sequentially` for widgets requiring individual key events. Form-input authorization and sensitive-field restrictions still apply. The engine verifies the resulting field value.
- `SEARCH`: observed GET search form only, with input authorization; fills/types then presses Enter. Reviewed POST submissions remain available through CLICK.
- `PRESS_KEY`: Tab, Shift+Tab, arrows, Escape, PageUp/PageDown, Home/End. Keys that can edit a focused form control require form-input permission. Activation keys and arbitrary shortcuts are excluded; activation uses the controller's reviewed CLICK/SEARCH paths.
- `SCROLL`: an observed target is centered to clear typical sticky headers; otherwise the engine advances 70% of the viewport in the requested direction. The next planning iteration inspects the newly revealed content. Lazy content marked `aria-busy` is awaited, within a deadline. `WAIT` can await further dynamic content. The model receives viewport text, headings, position and end-of-page state and is instructed to stop unproductive scrolling.
- `SCROLL_BACK`: restores the previous position in the active tab, with a bounded stack of 20 positions. Navigation history and tab controls remain separate. Scroll positions are session-local and are not restored after a worker restart.
- `WAIT`: waits for URL, document readiness, text, form value/state, focus, control visibility/expanded/busy state, scroll position or document height to change. State waits are capped at three seconds in the controller; no arbitrary sleep is added between replanning attempts. Existing job, model, navigation and recovery budgets remain enforced.

`expected_text` optionally specifies exact visible confirmation text. The engine waits for it and fails into replanning if absent. Without it, `interaction.verified` means only the stated check passed (UI change, focus, or input value), not that the user's entire objective succeeded. Final task completion still requires collected source evidence and the independent criterion verifier. Delayed content without usable state signals may require another bounded WAIT or replanning step.

Two identical interactions on unchanged state are allowed; a third is rejected even if the model changes its explanation. Failed-action fingerprints, bounded recovery attempts, task step limits and stagnation detection provide additional loop controls. Ambiguous mutations are never blindly replayed after worker failure.

## Observability and analytics

Agent step outcomes and `agent_action_completed` events carry a `trace` array: phase, epoch start/end timestamps, monotonic duration in milliseconds, and status. Loading, inspection, decision, action and waiting are distinguished. Traces also survive recoverable action failures. State signatures are hashed; transient field values are not written into interaction traces. Existing task decisions and screenshots retain their existing data-retention behavior.

The dashboard shows an expandable interaction timeline and the actual verification method/result for each action. Task responses include `traffic_kind: "automated"` and `automation_session_id`. Agent metrics are automation-only. Browser contexts send `X-AdBot-Automation: true` and `X-AdBot-Session: <job-id>`, alongside the existing `AdBotMonitor` user agent. Operators must filter these signals in their own server-side analytics to exclude automation from visitor reports; this application cannot reconfigure third-party analytics automatically. These markers identify automation, not authentication credentials.

## Verification

From `backend/`:

```sh
../.venv/bin/python -m pytest -q tests/test_interaction.py
../.venv/bin/python -m pytest -q
```

The local `/agent/interactions` laboratory exercises hover-only menus, focus and key events, Tab traversal, sticky navigation, two asynchronous infinite-scroll batches, disabled/covered controls, no-op loops, and delayed confirmations. Real Chromium verifies the resulting UI, navigation, trace timing and automation headers. The dashboard end-to-end journey opens the stored trace and checks its timestamp column. Existing goal-planning tests use a local model test double; live-provider planning quality remains unverified without credentials.

Validation on 2026-10-17: full backend suite 54 passed; final focused interaction/worker suite 8 passed (including one subsequently added keyboard-permission regression), covering 55 distinct backend tests overall. Frontend unit tests: 2 passed. Production build and Ruff checks passed. The only warning in the final backend runs was the existing Starlette/httpx TestClient deprecation. No database schema changes are required; interaction traces use existing JSON outcomes and events.

Final dashboard journeys: 2 passed, including expanding the interaction timeline and checking the UTC header, desktop screenshot, and mobile layout without horizontal overflow.
