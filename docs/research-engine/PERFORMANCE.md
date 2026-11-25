# Research performance

Quick Search uses two deterministic queries, bounded parallel HTTP retrieval and small evidence batches by default. It shares the browser worker capacity and uses browser rendering only for insufficient HTML when the operator enables the fallback. Conditional HTTP requests revalidate eligible expired cache entries. Claims reach the event stream after verification and persistence.

## Controlled measurement

Medians from six paired cold and warm Quick Search runs on the local SQLite worker. Each cold run received two source fixtures with a 30 ms simulated response delay. Search providers and the model used deterministic transport doubles. The browser fallback was disabled for this sample. Worker events and persistence used the actual queue.

| Measure | Cold cache | Warm cache |
| --- | ---: | ---: |
| First research event | 2.0 ms | 2.5 ms |
| First answer available to worker | 62 ms | 23 ms |
| Research stage duration | 62 ms | 23 ms |
| Source HTTP requests, including robots | 4 | 0 |
| Search-provider requests | 2 | 0 |
| Query cache hits | 0 | 2 |
| Document cache hits | 0 | 2 |
| Verification pass | 5.5 ms | 6.0 ms |
| Reported completion tokens | 96 | 96 |
| Chromium launches | 0 | 0 |

The fixture completed all twelve requests. It measures server-side behavior from worker execution, excluding queue wait, browser delivery, WAN latency and live model inference. The token sample comes from the model fixture.

The existing Website Agent completed five different Orion fixture tasks in 1.02–2.02 seconds of test-call time, each with a registered site and a real Chromium session. The two samples exercise different objectives, transports and timing boundaries. They show where browser launch and interaction enter the workflow and do not establish a speed ratio for comparable live requests.

## Reproduce and tune

Run `python -m pytest -q tests/test_research.py -k cold_warm` from `backend`. Run `python -m pytest -q tests/test_agent.py -k goal_driven_real_browser --durations=5` for the Website Agent fixture. Use `GET /api/research/v1/metrics` on an authenticated live deployment for task completion, provider request and latency totals, retrieval timings, first event, first verified answer, token accounting, verification and browser counters. Capture separate cold and warm distributions using representative real queries before changing execution limits.
