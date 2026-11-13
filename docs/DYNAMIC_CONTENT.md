# Dynamic website content

## Audit and implementation
The application is an operations dashboard, not an advertising storefront. Website registrations,
jobs, metrics, workflows, schedules and agent results already use authenticated APIs. There were
no production advertisement, pricing, FAQ, testimonial or media collections. The login headline,
introductory paragraph, dashboard headings, page descriptions and navigation labels were static.
These are now database-backed; operational field labels, instructions, branding and action names
remain application UI strings. The migration preserves the existing copy, including SEO defaults.

`content_sections` stores a key, order, editing status, draft JSON, independent published JSON and
update timestamp. JSON is restricted to title, description, image, image_alt, link, button and
canonical. Draft writes retain the prior publication. Publishing atomically replaces that snapshot;
archiving hides it; deletion removes it. This schema deliberately supports plain text only.

## Setup
1. Run `python -m alembic upgrade head` from `backend` using the configured database.
2. Set `ADBOT_CONTENT_ADMIN_KEYS` to a comma-separated subset of `ADBOT_API_KEYS` and restart
   the backend once. The empty default denies all content writes. Use a separate administrator key;
   never give it to ordinary workspace users. Keys must pass existing workspace authentication too.
3. Connect with an administrator key and open **Content**. Select a section, edit fields, inspect
   the preview, choose draft/published/archived and save. New custom keys create promotional sections
   displayed in order on the public login page. Use local image paths or HTTPS image URLs. The
   image field selects externally hosted media; this implementation does not upload or store files.

Reserved keys are `login`, `Overview`, `AI Agent`, `Websites`, `Jobs`, `Workflows`, `Schedules`,
and `seo`. Reserved key deletion/archive restores built-in heading defaults. Custom sections disappear.
Navigation destinations remain fixed for compatibility; their labels use the corresponding titles.
`seo` controls browser title, description, canonical link and Open Graph title/description/image.

## API and refresh
- `GET /api/content`: public ordered published snapshots only, no drafts or internal timestamps.
- `GET /api/admin/content?offset=0&limit=100`: authorized paginated editing records (max 200).
- `POST /api/admin/content/{key}`: authorized upsert with `{status, position, draft}`.
- `DELETE /api/admin/content/{key}`: authorized deletion.

Existing no-store HTTP responses prevent private cache sharing. React Query deduplicates public
requests, polls every 30 seconds, and refetches on focus; successful editor writes invalidate the
public query immediately. Separate browsers see updates on their next successful refresh. Failed
refreshes retain cached content; initial failure uses original copy and an accessible retry notice.
Unknown fields, statuses, excessive lengths and unsafe URL schemes are rejected. React escapes
all content; no raw HTML is inserted. Normal workspace authentication and rate limits protect admin
routes; administrator grants are global because site content is global, not workspace-private.

## Verification and limits
Tests cover snapshot isolation, publication, archive, delete, unauthorized writes, URL validation,
seed integrity, repeated migration, escaped rendering, empty sections and browser publication.
Run backend pytest from `backend`, frontend `npm test`, `npm run build`, and `npm run test:e2e`.
The browser runner uses an isolated temporary database; it does not modify production content.

This remains a client-rendered Vite application. Initial HTML retains the original SEO fallback;
dynamic metadata requires JavaScript. SSR metadata/social-crawler verification is not implemented.
The editor displays up to 200 sections; the API supports additional pages. No asset upload service,
revision history, simultaneous-editor conflict protection or free-form navigation routing is added.
Production readiness requires deployment verification with PostgreSQL/Redis, the actual reverse
proxy and image hosting/CSP, plus resolution of any existing unrelated regression failures.

### Recorded verification (2026-11-13)
- Targeted content backend tests: **5 passed**, including migration replay and sanitized DB failures.
- Frontend Vitest: **4 passed** across API and content rendering tests.
- TypeScript + Vite production build: **passed**, including a second build after frontend adjustments.
- Ruff on content code, model/router changes, migration and content tests: **passed**.
- `git diff --check`: **passed**.
- Broader backend non-browser run: **38 passed, 1 failed, 28 deselected**. The failure was an
  existing security test assuming deterministic retry delay despite the workspace's jitter behavior.
  Its assertion was updated to the intended bounded jitter range; see focused rerun result below.
- Playwright: **4 failed**. Agent browser launch timed out at 180 seconds; both content tests timed
  out creating their page; the existing crawl journey timed out on initial navigation. API readiness
  and Vite startup succeeded. These failures do not verify the content browser assertions, responsive
  behavior, or SEO DOM assertions. End-to-end production readiness is **not confirmed**.
- Small existing indentation errors in browser retry/scroll logic and agent scrolling were repaired
  to permit broader test collection, preserving the workspace's pre-existing behavioral changes.
- Focused retry/security rerun after adjusting the jitter assertion: **1 passed**. The full broad
  suite was not rerun after this test-only change; the previous 38 passes remain the available evidence.
