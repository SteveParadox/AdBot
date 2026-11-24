# Research and implementation decisions

Primary documentation and source were checked on 24 November 2026. No third-party
implementation source was copied; no dependencies were added.

| Reference | Applied decision |
| --- | --- |
| [TanStack Query cancellation](https://tanstack.com/query/v5/docs/framework/react/guides/query-cancellation) | Consume query AbortSignals, cancel obsolete subscribers independently, and prevent late snapshots from overwriting streamed state. |
| [TanStack cache updates](https://tanstack.com/query/v5/docs/framework/react/guides/updates-from-mutation-responses) | Update authoritative cached rows/steps; fetch narrowly when payloads are incomplete. |
| [TanStack defaults](https://tanstack.com/query/v5/docs/framework/react/guides/important-defaults) | Keep the installed library; use explicit freshness, five-minute cache GC and conditional fallback intervals. |
| [SWR performance](https://swr.vercel.app/docs/advanced/performance) | Shared query identity and deduplication are useful patterns; introducing a second cache library would duplicate responsibility. |
| [React Strict Mode](https://react.dev/reference/react/StrictMode) | Preserve development checks; give shared connections and pending transports brief, bounded cleanup grace periods. |
| [FastAPI StreamingResponse](https://fastapi.tiangolo.com/advanced/custom-response/) and [Starlette disconnect handling](https://starlette.dev/requests/) | Retain authenticated fetch-based SSE, close sessions before yielding, and release streams on disconnect. |
| [MDN SSE protocol](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events) | Parse framing, comments and replay cursors; use heartbeats, watchdogs and bounded reconnects. Avoid placing bearer credentials in a stream URL. |
| [Redis Pub/Sub](https://redis.io/docs/latest/develop/pubsub/) and [Redis Streams](https://redis.io/docs/latest/develop/data-types/streams/) | Plain Pub/Sub alone would lose offline messages. SQL already provides durability and cross-process visibility; a new mandatory broker is not justified by these workloads. |
| [Browser Use lifecycle hooks](https://github.com/browser-use/browser-use/blob/main/skills/open-source/references/agent.md) | Existing Adbot observed/decision/completed boundaries are sufficient event sources; avoid replacing its browser agent. |
| [Grafana Live](https://grafana.com/docs/grafana/latest/setup-grafana/set-up-grafana-live/) | Multiplex resource updates through one frontend-owned connection; no bidirectional requirement justifies WebSockets. |
| [Temporal Event History](https://docs.temporal.io/encyclopedia/event-history) | Treat durable history and recovery as separate from transient delivery; retain replay and reconciliation without adopting an orchestration platform. |
| [Apache Iggy](https://github.com/apache/iggy) | Its durable streaming/consumer-offset model is relevant at larger scale, but adding a server and SDK would create unnecessary operations and platform dependencies here. |

Conditional HTTP/ETags were considered. Eliminating reads is more useful than
conditionally reissuing them for these resources. Protected responses retain the
existing no-store policy; client caches remain authorization-scoped and ephemeral.
The workload does not justify new HTTP cache semantics or optimistic writes that
could misrepresent pending browser operations.
