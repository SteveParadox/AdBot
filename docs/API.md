# API and workflow reference

All endpoints except health/readiness and OpenAPI require
`Authorization: Bearer YOUR_KEY`. Do not put keys in URL query strings.
Collections return `{ "items": [...], "total": 123 }` and support `offset` and
`limit` (1–200). Resource IDs are UUIDs. Timestamps in responses are UTC epoch
seconds. Unauthorized resource lookup returns 404.

| Method | Path | Purpose |
| --- | --- | --- |
| POST / GET | `/api/websites` | Register / list targets |
| GET / PATCH / DELETE | `/api/websites/{id}` | Inspect / replace configuration / delete |
| POST / GET | `/api/jobs` | Enqueue / list jobs |
| GET | `/api/jobs/{id}` | Job state and discovered count |
| POST | `/api/jobs/{id}/cancel` | Request prompt cancellation |
| POST | `/api/jobs/{id}/pause` | Pause at next safe checkpoint |
| POST | `/api/jobs/{id}/resume` | Resume checkpoint execution |
| POST | `/api/jobs/{id}/retry` | Create a new run for failed/cancelled reads |
| GET | `/api/jobs/{id}/pages` | Page results, `q` URL search, `http_status` filter |
| GET | `/api/jobs/{id}/logs` | Persisted events, `after` cursor |
| GET | `/api/jobs/{id}/events` | SSE, Last-Event-ID header / `after` cursor |
| GET | `/api/artifacts/{filename}` | Authenticated PNG capture |
| POST / GET | `/api/workflows` | Create / list workflows |
| PATCH / DELETE | `/api/workflows/{id}` | Versioned edits / delete |
| POST / GET | `/api/schedules` | Create / list schedules |
| PATCH / DELETE | `/api/schedules/{id}` | Pause, resume, edit timing / delete |
| GET | `/api/analytics/overview` | Totals, statuses, response distribution, 30-day trend |
| GET | `/api/analytics/websites` | Per-website job/page/discovery totals |
| GET | `/api/health` | Process liveness |
| GET | `/api/ready` | Database schema and Redis readiness |

PATCH website/workflow requests use their complete creation schema. Schedule
PATCH accepts partial `enabled`, `cron_expression`, `timezone` and `run_at`.
Workflow identity stays associated with its original website. Website deletion
requires all jobs to be terminal and removes related history. Workflow deletion
requires dependent schedules to be removed first.

## Register a target

```json
{
  "name": "Documentation monitor",
  "base_url": "https://example.com/",
  "allowed_domains": ["example.com"],
  "authorized": true,
  "configuration": {
    "max_pages": 10,
    "max_depth": 2,
    "delay_seconds": 2,
    "max_duration_seconds": 600,
    "navigation_timeout_ms": 30000,
    "browser": "chromium",
    "viewport": "desktop",
    "headless": true,
    "screenshots": true,
    "scroll": false,
    "discover_links": true,
    "respect_robots": true,
    "retries": 2,
    "allowed_patterns": ["https://example.com/*"],
    "excluded_patterns": ["*/logout*"],
    "wait_until": "domcontentloaded",
    "wait_selector": null
  }
}
```

Omitted configuration values use validated defaults. Maximum pages is 1000;
depth is 10; session length is 3600 seconds; navigation timeout is 120 seconds;
retry budget is 5. Delay is at least 0.1 seconds. URL patterns use shell-style
globs on normalized absolute URLs, not regular expressions. `*.example.com`
allows subdomains, not the apex. Add both if you need both.

## Enqueue

`POST /api/jobs` body:

```json
{"website_id": "TARGET_UUID", "workflow_id": null}
```

Include an `Idempotency-Key` header (maximum 160 characters) and reuse it when
retrying the same submission. A workflow ID selects workflow mode; null crawls.
Jobs snapshot configuration and workflow versions. HTTP 201 means queued, not
browser execution completed. Cancelling a queued job is immediate; running jobs
observe cancellation within their control loop and then release the browser.

## Workflow

```json
{
  "website_id": "TARGET_UUID",
  "name": "Check documentation",
  "enabled": true,
  "definition": {
    "schema_version": 1,
    "steps": [
      {"action": "ASSERT_VISIBLE", "selector": "h1"},
      {"action": "EXTRACT_TEXT", "selector": "h1"},
      {"action": "SCROLL", "pixels": 600},
      {"action": "SCREENSHOT"},
      {"action": "STOP"}
    ]
  }
}
```

| Action | Parameters / behavior |
| --- | --- |
| OPEN_URL | `url`; validated and recorded as a visit |
| WAIT | `seconds` 0–60; set `timeout_ms` above the wait duration |
| WAIT_FOR_SELECTOR | `selector`; waits for a visible locator |
| CLICK | `selector`, `authorized: true`; links must stay allowed, non-links require `data-adbot-safe="true"`; forms blocked |
| SCROLL | `pixels` 0–10000, or optional `selector` |
| EXTRACT_TEXT | `selector`; stores up to 10000 characters in event details |
| EXTRACT_LINKS | Stores up to 500 allowed links in event details |
| SCREENSHOT | Saves bounded viewport capture; path in event details |
| ASSERT_VISIBLE | `selector`; fails if not visible |
| ASSERT_TEXT | `selector`, `text`; asserts substring |
| NAVIGATE_BACK | Revisits previous durable workflow URL |
| STOP | Ends the workflow |

Each action accepts `timeout_ms` (100–60000, default 10000). Actions use the
first matching Playwright locator. Selector syntax and existence are checked
during execution; no browser preflight runs in API requests. Unknown actions and
fields are rejected, including arbitrary JavaScript/Python. Extracted results
are in job logs. A workflow has at most 100 steps.

## Schedules

Recurring:

```json
{"website_id":"TARGET_UUID","cron_expression":"0 8 * * 1","timezone":"Africa/Lagos","enabled":true}
```

One-time:

```json
{"website_id":"TARGET_UUID","run_at":"2026-12-01T08:00:00+01:00","timezone":"Africa/Lagos","enabled":true}
```

Use a future timezone-aware `run_at`. Cron uses five fields and IANA timezone
names. `PATCH {"enabled":false}` pauses; `PATCH {"enabled":true}` resumes and
recomputes the next recurring occurrence. Disabled one-time schedules can be
rescheduled by supplying a new future `run_at`.
