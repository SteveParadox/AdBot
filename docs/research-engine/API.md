# Research API

Versioned routes use `/api/research/v1`. Supply the workspace bearer credential on each request, including SSE connections. Cross-workspace resource IDs return 404. The events stream accepts `Last-Event-ID` or `after` for replay. Lists accept `offset` and `limit`.

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
| POST | `/tasks/{id}/retry` | Create a new attempt after partial, failed or cancelled research. |
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
