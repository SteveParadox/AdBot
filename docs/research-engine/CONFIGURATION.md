# Configuration and deployment

Set `ADBOT_RESEARCH_ENABLED=true` in the API and worker environment. Configure an existing AI provider to generate and verify synthesized claims. Then configure at least one search provider. A provider-free deployment can use Direct Answer when a model is available, and can retrieve an explicitly supplied public URL.

| Setting | Default and effect |
| --- | --- |
| `ADBOT_RESEARCH_ENABLED` | `false`. Opts in to public research. |
| `ADBOT_RESEARCH_SEARXNG_URL` | Empty. Base URL of an operator-managed SearXNG server. |
| `ADBOT_RESEARCH_BRAVE_KEY` | Empty. Enables Brave Search when configured. |
| `ADBOT_RESEARCH_TAVILY_KEY` | Empty. Enables Tavily when configured. |
| `ADBOT_RESEARCH_EXA_KEY` | Empty. Enables Exa when configured. |
| `ADBOT_RESEARCH_SERPER_KEY` | Empty. Enables Serper when configured. |
| `ADBOT_RESEARCH_PROVIDER_ORDER` | `searxng,brave,tavily,exa,serper`. Use a comma-separated list without spaces. |
| `ADBOT_RESEARCH_PROVIDER_TIMEOUT` | 8 seconds per search transport operation. |
| `ADBOT_RESEARCH_PROVIDER_RPM` | 60 requests per provider identity per minute across workers. |
| `ADBOT_RESEARCH_FETCH_TIMEOUT` | 8 seconds per source transport operation, within the task deadline. |
| `ADBOT_RESEARCH_CACHE_SECONDS` | 300 seconds. Shopping and freshness-sensitive documents use at most 60 seconds. Origin cache directives can shorten that window. |
| `ADBOT_RESEARCH_PARALLELISM` | 4 parallel operations per research task. |
| `ADBOT_RESEARCH_EXCLUDED_DOMAINS` | Empty. Comma-separated exact hosts or `*.example.org` patterns for public source access. |
| `ADBOT_RESEARCH_BROWSER_ENABLED` | `false`. Enables optional Chromium fallback. The worker image includes Chromium, and the runtime must support its sandbox. |
| `ADBOT_RESEARCH_BUDGETS` | Empty JSON object. Keys select individual mode overrides. |
| `ADBOT_AI_PROVIDER`, `ADBOT_AI_MODEL` | Use the existing Groq, Ollama or compatible configuration. See the repository's provider settings. |

For example, a Quick Search budget override in a shell environment is:

```bash
export ADBOT_RESEARCH_BUDGETS='{"quick":{"seconds":45,"requests":4,"pages":5,"rounds":1,"calls":4,"tokens":22000,"browsers":1}}'
```

Budgets are stored at submission. They bound the research deadline, provider requests, candidate pages, iterations, model attempts, charged tokens and browser fallback attempts. Direct Answer has a zero network budget. Auto selects a resolved mode. Website Agent opens the existing website workspace.

## Self-hosted SearXNG

Run a SearXNG instance you control. Configure its secret, supported upstream engines and request limits. Enable its JSON search format in `settings.yml`:

```yaml
use_default_settings: true
search:
  formats:
    - html
    - json
```

Place SearXNG on a network reachable from the Adbot worker. An example on a shared Docker network is `ADBOT_RESEARCH_SEARXNG_URL=http://searxng:8080`. The setting is an operator-defined trust boundary. Search-provider credentials are supplied to their respective API, and source retrieval uses a separate credential-free connection.

If outbound routing is enabled, add a `research` service to the private routing file for public documents and paid providers. Choose an explicitly direct route or a fixed approved proxy. Configure `research_local` as `{"mode":"direct"}` for the trusted SearXNG service. Missing routes fail closed. `ADBOT_AUTHORIZED_DOMAINS` remains the website-agent authorization policy. The operator separately opts in to public research and may set research exclusions.

## Deploy and troubleshoot

1. Configure the environment and take a database backup before upgrading an existing deployment.
2. Rebuild and start the compose services with `docker compose up -d --build`. The migration service must finish before the API and worker start. For manual deployments run `python -m alembic upgrade head` from `backend`.
3. Open `/research`, connect with the workspace key and submit a Quick Search query without a URL.
4. Check `/api/research/v1/providers` with an authenticated request and inspect the research timeline if a provider returned errors.
5. A SearXNG 403 can indicate JSON output is disabled, a limiter rejected the request, or the service requires different routing. Start with the instance settings and logs. A sustained 429 opens the adapter cooldown and can trigger configured fallback.
6. Browser fallback requires a compatible Chromium sandbox. On Linux containers, run the worker as a non-root user with a seccomp profile that supports the Chromium sandbox. If Chromium cannot start securely, Adbot keeps any available HTTP result. [Playwright container guidance](https://playwright.dev/python/docs/docker)
