# Research API

Versioned routes use `/api/research/v1`. Supply the workspace bearer credential on each request, including SSE connections. Cross-workspace resource IDs return 404. The events stream accepts `Last-Event-ID` or `after` for replay within the signed 64-bit cursor range. Lists accept `offset` and `limit`.

| Method | Path | Behavior |
| --- | --- | --- |
| POST | `/query` | Queue a research question and return its task and conversation IDs. |
| GET | `/tasks` | List workspace research jobs. |
| GET | `/tasks/{id}` | Read the job state, resolved intent, budget and result. |
| GET | `/tasks/{id}/events` | Stream progress and verified answer segments. |
| GET | `/tasks/{id}/sources` | Inspect retrieved public sources and timestamps. |
| GET | `/tasks/{id}/evidence` | Inspect quotations and extracted facts. |
| GET | `/tasks/{id}/search-results` | Inspect normalized search candidates. |
| POST | `/tasks/{id}/cancel` | Request cancellation. A running worker acknowledges it asynchronously. |
| POST | `/tasks/{id}/retry` | Create a new attempt after partial, failed or cancelled research using the original resolved mode and preceding conversation turns. |
| GET, POST | `/conversations` | List or create conversations. |
| GET, DELETE | `/conversations/{id}` | Read paginated turns or delete an inactive conversation. |
| POST | `/conversations/{id}/messages` | Append a turn. One turn can be active per conversation. |
| GET | `/providers` | List configuration and last observed provider outcomes in the workspace. |
| GET | `/metrics` | Read up to 50 terminal research outcomes and completed-task metric samples. |

The query body accepts `question`, `mode`, optional `country` (two-letter uppercase), optional `freshness` (`day`, `week`, `month`, `year`) and optional `conversation_id`. Modes use `auto`, `direct`, `quick`, `deep`, `shopping`, `fact_check` and `technical`. Website Agent uses the existing agent routes and a registered website.

```bash
curl -sS 'http://localhost:8000/api/research/v1/query' \
  -H "Authorization: Bearer ${ADBOT_WORKSPACE_KEY}" \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: quantum-quick-1' \
  --data '{"question":"What are the latest developments in quantum computing?","mode":"quick","freshness":"month"}'
```

Submit an optional `Idempotency-Key` to replay the original result of a query, message or retry after an ambiguous response. Reusing the key with different input returns 409. A successful submission returns 202. A task can be `completed` with a result quality of `partial`. The result's `notes` explain missing sources, dates or verified claims. `failed` and `cancelled` are distinct execution states.

`answer_chunk` contains checked Markdown segments. The final `completed` event and persisted answer are committed together. Only accepted claims render inline cited links, with URLs derived from the stored source IDs.


### PDF provenance

PDF sources carry metadata.document_type = "pdf", page_count, pages_examined,
pages_with_text, and extraction_truncated. PDF evidence includes a physical
one-based page number and a location such as
pdf:page-2:line-3:sentence-1 or pdf:page-2:table-1:row-2.
Citation URLs append #page=N to the retrieved source URL; the source itself
remains identified by its original URL and content hash.
Table evidence uses normalized observed cells, optionally with the observed
first row. Existing evidence IDs and verification semantics are unchanged.

### Conversation context

Completed tasks expose `result.conversation_context` (anchor_id, references,
unresolved, constraints, country, freshness) and versioned
`result.conversation_memory`. These are output-only fields; clients cannot
supply arbitrary memory snapshots. References use original one-based result
positions. Retries reuse the original server-side context. Use explicit
phrases such as "product 7", "source 12", "drop RAM requirement", or
"new topic" to resolve or reset supported context.
