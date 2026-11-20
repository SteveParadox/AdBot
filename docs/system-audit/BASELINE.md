# Repository baseline before audit remediation

Captured 2026-11-19 before changing application code for this audit.

- Branch: `main`.
- HEAD: `f1505355d251f040c88169b28f9c359904ce1cda` (merge of agent 500-step/autonomous-click work).
- Recent commits: `99ab9a6` agent ceiling/click behavior; `1414020` Qwen fallback/recovery; `6e3da4e` polling/rate-limit behavior; `7c8f573` coordinated automation/admin; `08a5b66` atomic content revisions.
- Substantial existing uncommitted changes cover concurrency, extraction, planning, browser profiles and accessibility. These implementations are in the working tree, not the HEAD commit. Untracked migrations/modules/tests/reports are part of the inspected baseline. Unrelated `.vscode`, prompt/todo/batch files and the existing `docs/OPERATIONS.md` modification are preserved.
- No repository AGENTS.md was found by the initial file inventory. Repository architecture/API and prior verification reports are being checked against executable code rather than accepted as proof.
- Initial Ruff application/fixture checks and `git diff --check`: passed.
- Initial frontend Vitest: 6 files, 18 tests passed. Production build started; its completion is recorded in the audit verification log.
- Existing runtime: Windows, Python 3.11.2; Playwright and browser installation checked separately. Existing backend requirements pin Playwright 1.56.0 while prior local reports identify 1.56.1; environment drift is a release verification consideration.

Prior reports record local fixture successes and disclose missing live-model quality evaluation, external Redis/PostgreSQL/egress certification, manual assistive-technology testing and generic natural-language export semantics. Those are historical evidence, not fresh passes for this audit. The audit will execute full available regression and integration checks after remediation.

Initial execution-path review found real implementations behind dataset schemas/runs/exports, task planning/steps/evidence, semantic resolution/native input and SQL lease-fenced worker execution. Reproduction work will specifically challenge dedupe after state reversion, empty-capture success/removal, export consistency, privacy-sensitive semantic identity, and cross-feature workflow boundaries.
