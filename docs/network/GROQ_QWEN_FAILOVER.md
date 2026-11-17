# Groq to local Qwen fallback

Groq remains primary. A task switches to its configured local fallback when Groq returns an HTTP
error (including 429), times out, fails transport/schema validation, or cannot reserve its primary token
budget. There is one primary attempt when fallback is enabled; the Groq Retry-After delay is not waited
out before trying local inference. After a switch, that ModelClient stays local for the remaining task.

Successful Groq responses are still used. If their remaining-request count is at most one, or remaining
tokens are below the conservative next-call estimate (prompt characters / 3 + maximum output tokens),
the next decision uses local inference. Missing or malformed headers do not invent a quota warning.
This uses [Groq rate-limit response headers](https://console.groq.com/docs/rate-limits), not a claim
that the client can predict every provider limit or another worker's consumption.

## Configuration

```dotenv
ADBOT_AI_PROVIDER=groq
ADBOT_AI_FALLBACK_PROVIDER=local
ADBOT_AI_FALLBACK_MODEL=qwen3:4b
ADBOT_AI_FALLBACK_BASE_URL=http://127.0.0.1:11434/v1
ADBOT_AI_OLLAMA_NATIVE=true
ADBOT_AI_PRIMARY_FALLBACK_TIMEOUT_SECONDS=10
ADBOT_AI_FALLBACK_TIMEOUT_SECONDS=120
ADBOT_AI_OLLAMA_WARMUP_TIMEOUT_SECONDS=300
ADBOT_AGENT_FALLBACK_TOKENS=20000
```

Restart API and worker after environment/code changes. Keep Ollama running. Native mode is an explicit
operator declaration that local model endpoints use Ollama. It sends /api/chat with the actual response
JSON schema, think:false, stream:false, an 8192-token context and persistent keep_alive. Groq continues
to receive OpenAI-compatible requests. Native inference passes through the existing approved local
routing policy and preserves strict schema validation. Native mode uses the textual page observation,
not screenshots, for the text-only backup. Phase-specific extraction/completion/verification prompts
and schema validation feedback improve compatibility without bypassing goal/evidence checks. See [Ollama thinking controls](https://docs.ollama.com/capabilities/thinking).

The worker warms the local fallback before claiming jobs and reports warming/startup readiness in its heartbeat and dashboard worker card.
Warm-up is bounded and shutdown-cancellable. A failed warm-up is logged/reported; it does not prove the
backup is available. An HTTP error is handed off immediately after it is observed. Unresponsive Groq
calls are bounded by the primary fallback timeout, while the existing total session budget still applies.

On the verified machine Qwen runs on CPU and an observed cold load took approximately 103 seconds.
Preloading moves that cost to worker startup. Immediate routing does not mean zero-time local generation.
Model eviction, service restarts, insufficient RAM and concurrent local requests can still add delay.
Qwen3:4b is a text fallback; tasks requiring vision need a compatible model or an explicitly reviewed
text-only workflow. A fallback cannot bypass approvals, task time/step/token limits or revive an already
failed task. The local setup reserves 20000 task tokens for fallback (within the existing total task budget).
Size the reserved fallback token budget for your workload; the conservative reservation
must cover the next prompt and output.

## Reproducible checks

From backend:

- python -m pytest tests/test_provider_handoff.py tests/test_agent.py -q -m "not browser"
- python -m testsupport.probe_qwen_fallback (simulated Groq 429, real local Ollama)
- Set ADBOT_TEST_LOCAL_QWEN=1 and run python -m pytest tests/test_local_qwen.py -q.

The opt-in integration test uses a temporary database, controlled local fixture browser, simulated
Groq exhaustion and real Qwen decisions/verification. It never spends live Groq quota or browses a real
third-party site. The real end-to-end browser handoff passed on 2026-11-17 in 131.35 seconds:
one simulated Groq 429, real Qwen extraction, completion with the stored evidence ID, independent
verification and a completed job under the original ID. Initial probes exposed cold-start timeouts,
missing action arguments, repeated extraction and inconsistent verification; the final native-mode,
phase-specific prompts and verification schema ordering fixed the exercised fixture case.

Final focused regressions passed (34 tests), and the separate real-Qwen probe correctly rejected an
unsupported claim. The readiness UI build and all 7 frontend unit tests passed. Details are recorded in
[automation test results](../automation/TEST_RESULTS.md). These controlled results are not a guarantee
that a 4B local model will solve every task or match Groq's reasoning quality.
