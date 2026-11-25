# Cloud provider failover

The configured local deployment uses this order:

1. Existing Groq key - `openai/gpt-oss-120b`.
2. OpenRouter - `openai/gpt-oss-120b`.
3. Google AI Studio - `gemini-3.8-flash`.
4. NVIDIA - `nvidia/nemotron-3.5-lightning-30b-a3b`.
5. Additional Groq key - `openai/gpt-oss-120b`.

Keys belong in the ignored root `.env`; `.env.example` contains placeholders only.
`ADBOT_AI_PROVIDER=groq` and
`ADBOT_AI_PROVIDER_ORDER=groq,openrouter,google,nvidia,groq_secondary`
select the chain. Use the provider-specific `*_API_KEY`, `*_BASE_URL` and `*_MODEL`
settings shown in the example. The first provider uses `ADBOT_AI_MODEL`.
The additional Groq key is a separate credential, not a model identifier. Keys in
the same Groq organization may share limits; cross-provider backups remain useful.

The previous Qwen model, integration probe and model-specific test have been
removed. Historical audit reports describe earlier configurations only. Generic
local-provider support is still available when explicitly configured.

Each chain entry gets one attempt per request, regardless of `ADBOT_AI_RETRIES`.
HTTP errors, rate limits, transport/protocol failures, response size limits and
invalid JSON/schema/usage metadata advance immediately to the next entry, with no
backoff or Retry-After sleep. The same system instructions, objective, observation,
schema and task deadline are retained; switching inference providers does not
replay browser actions. The task stays on its selected provider while it works. If it fails, the client
tries the remaining providers and wraps to earlier providers whose cooldowns have
expired. Each provider is considered once per request; no failed attempt is
immediately replayed. New tasks start from the top and skip providers under a
shared SQL cooldown. A successful response with near-exhausted
quota is used, then the next request moves to the following provider.

`ADBOT_AI_PRIMARY_FALLBACK_TIMEOUT_SECONDS=10` caps the entire request for each
provider in a cloud chain, including streamed response reading. A silent outage
therefore takes up to ten seconds to detect; errors that arrive sooner switch
immediately. A legacy single-provider/local fallback configuration retains
`ADBOT_AI_FALLBACK_TIMEOUT_SECONDS` for its final provider. All attempts remain
bounded by the task deadline and token budget.
`ADBOT_AI_FAILURE_COOLDOWN_SECONDS=30` controls the shared failure cooldown;
a longer provider Retry-After is preserved. If all providers are temporarily unavailable, inference waits for the earliest
reported retry time and retries the same request, within the original task
deadline. These waits do not consume browser steps, create recovery subtasks, or
replay browser actions. Cancellation and pause controls remain effective. Permanent
errors across all providers stop with a provider-by-provider error summary.

Provider failure events now identify the provider, model and failure reason;
`model_waiting` events expose the temporary cooldown. Authentication tokens and
provider response bodies are never included. `ADBOT_AI_REASONING_EFFORT=low`
reduces GPT-OSS reasoning overhead on Groq and OpenRouter. Truncated output is
reported explicitly before trying another provider. See the provider references
for [Groq reasoning](https://console.groq.com/docs/reasoning) and
[OpenRouter reasoning](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens).

Remote backups use the `ai` egress/User-Agent policy and retain public-address,
HTTPS, TLS and no-redirect checks. Only explicitly local providers use `ai_local`.
All new credential fields are included in log redaction. Restart API and workers
after changing provider settings; an existing process caches its settings.

Provider protocols: [OpenRouter](https://openrouter.ai/docs/api/reference/overview),
[Google OpenAI compatibility](https://aistudio.google.com/docs/openai),
[Groq models](https://console.groq.com/docs/models), and
[NVIDIA model catalog](https://integrate.api.nvidia.com/v1/models).

Regression coverage is in `backend/tests/test_cloud_failover.py` and
`backend/tests/test_provider_handoff.py`. It uses isolated databases, fixture-only
credentials and mock HTTP transports. No real provider credentials are used by
those tests. The separate live checks made small inference calls without browser
actions or private task content.


Live verification on 2026-11-24: both Groq credentials, OpenRouter and NVIDIA
returned HTTP 200 with the requested JSON. Google `gemini-3.8-flash` returned
HTTP 503 (temporary high demand), so successful Google inference remains
unverified. A separate ModelClient probe simulated outages for Groq and
OpenRouter, received Google's real 503, and completed the same request on live
NVIDIA. It used a temporary database and made no browser actions.

The browser regression also completed a local research task after a successful
initial plan, a simulated Groq 429, an OpenRouter 503, and invalid Google JSON.
The NVIDIA test double continued extraction and independent verification under
the same task identifier. Playwright process startup required running this test
outside the filesystem sandbox; the initial sandbox attempt was denied by Windows.

Final validation: the focused non-browser suite passed 149 tests (16 browser
cases deselected); the new browser failover workflow passed separately. Ruff and
`git diff --check` passed. This is local verification, not hosted CI.


Follow-up for the reported Xavkit failure: the final backup previously pinned a
ModelClient to the end of its list, so an outage there could never revisit an
earlier recovered provider. Shared cooldown errors then reached browser replanning
and exhausted the task recovery budget. Cloud failover now wraps once through
all candidates; temporary chain outages wait within `ask_model`, preserving the
inference payload, browser step, plan and original deadline. Permanent chain
failures stop with individual provider reasons.

Follow-up validation on 2026-11-24: 122 non-browser regression tests passed, both
cloud browser workflows passed, and four focused reasoning/Retry-After/pause
checks passed (two overlap the 122-test run). Ruff, diff whitespace and secret
checks passed. A live decision-schema probe returned a valid EXTRACT decision in
about 2.3 seconds. Both Groq keys, OpenRouter and NVIDIA passed fresh simple
inference checks; Google continued to return HTTP 503. The idle local worker was
restarted after checking that no jobs were queued or active. The original failed
task and its diagnostics were retained.


Response-contract follow-up on 2026-11-25: replaying the saved failing request
reproduced Groq returning `claims: null` for a non-completion action, and NVIDIA
spending all 800 completion tokens on reasoning with no answer content. The
adapter now requests strict JSON-schema output for the configured GPT-OSS and
NVIDIA Lightning models. Wire object fields are required and closed; all local
action, citation and authorization validators still run. Dynamic extraction
maps retain JSON-object mode so caller-defined field names are preserved.

Explicit null optional collection fields use their existing empty collection
default. Required fields, missing click targets, and completion without evidence
claims remain invalid. JSON fences and executable text remain rejected. Validation
failure events identify field paths and error types without storing the returned
content or sensitive input values.

The default and local `ADBOT_AI_MAX_OUTPUT_TOKENS` are now 2048, and that complete
allowance is reserved before dispatch. `ADBOT_NVIDIA_THINKING_ENABLED=false`
disables Lightning's reasoning trace so the answer can use the output budget.
See [NVIDIA's reasoning controls](https://docs.nvidia.com/nim/large-language-models/2.0.10/get-started/advanced/get-started-nemotron-3.5-lightning)
and [Groq structured outputs](https://console.groq.com/docs/structured-outputs).
Live replay with the new settings produced validated decisions from both Groq
keys, OpenRouter and NVIDIA. NVIDIA reported zero reasoning tokens and a normal
stop, rather than truncation. Google continued returning HTTP 503.

Validation for the response-contract follow-up: the initial non-browser run had
124 passes and one wall-clock-sensitive Retry-After assertion failure. That test
now uses a fixed monotonic clock; the focused 16-test rerun passed, including the
new extraction-map compatibility case. A first browser run timed out before its
first model call; an isolated Chromium startup check then passed, and a fresh
run of all three response/failover browser workflows passed in 26.62 seconds.
Ruff and diff whitespace checks passed. Both idle local workers were reloaded
with the fix, preserving the existing worker count.
