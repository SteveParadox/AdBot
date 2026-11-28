# Continuous learning scaffold

Status: offline feedback contracts and paired fixture evaluation. No training, self-modification, automated promotion, or live learning hooks.

## Boundaries
- Begin with verified feedback for authorized information retrieval, extraction accuracy and report quality. Record outcome, rubric version and provenance; avoid collecting credentials, sensitive session data or raw personal data.
- Treat lessons as untrusted candidate hypotheses. Keep training/validation/held-out fixtures separate, prevent duplicate trajectories crossing splits, and compare candidates with a pinned baseline.
- Evaluation metrics include correctness, citation fidelity, completeness, latency and cost; require regression checks, representative holdout cases, review and rollback before a change.
- The pure review gate only demonstrates a minimal quality check; it is not a production acceptance policy or statistical significance test.
- Do not update model weights, prompts, permissions or execution policy automatically. No online exploration or unreviewed deployment.

## Next implementation
Build controlled offline fixtures and a versioned evaluation harness (AdbotGym), record opt-in redacted task feedback, compare candidate summaries on frozen suites, and document approval and rollback procedures. Consider offline fine-tuning only after sufficient validated data and governance.

## Additional reference implementation

`compare_fixture_outcomes` computes baseline and candidate pass rates and exact regression/improvement IDs from the same fixture manifest; manifest identity is hashed. Fixture IDs alone do not prove that fixture content is frozen or that results were independently verified. See `test_cognition_paired_evaluation.py`. Design references: https://github.com/openai/evals and https://docs.langchain.com/langsmith/evaluation-types.
