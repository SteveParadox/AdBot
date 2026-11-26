# Advanced autonomous search interfaces

The default autonomous read-side search permission supports native GET forms, form-less searchboxes, accessible comboboxes, contenteditable search widgets, scoped search buttons and dynamic suggestions. The agent uses the browser's existing live element binding. It waits for relevant rendered content, busy indicators and bounded XHR/fetch activity rather than treating input-value changes as successful retrieval.

Associated suggestion lists are inspected. A unique exact matching suggestion can be selected within the same search scope; ambiguous alternatives remain visible for further inspection or objective-derived query refinement. No site-specific selectors or endpoint guessing is used.

## Read-only POST search

POST endpoints cannot be verified as non-mutating by observing a name, HTTP status or HTML form. The operator must independently confirm the endpoint's server-side behavior before explicitly approving it. In the agent form, expand **Approved read-only POST search**, enter its exact URL and query field, and attest that the endpoint is read-only. The API accepts up to eight approvals:

```json
{"approved_post_search":[{"url":"https://example.com/api/search","query_field":"q","verified_read_only":true}]}
```

The runtime enforces exact approved URLs, website policy, main-frame association, bounded time and request count, a query-only JSON or URL-encoded body matching the active search, and no POST redirects. General mutation permission is not granted. Additional payload fields, CSRF tokens, multipart bodies, nested GraphQL operations, unapproved endpoints and write methods are not supported by this default permission. GET interfaces still require operator-authorized websites; HTTP GET alone cannot establish the absence of server-side effects.

## Testing

Run `pytest -q tests/test_extraction_first_discovery.py tests/test_category_enumeration.py` in the backend, including browser tests. The new fixtures exercise dynamic suggestions with an editable DIV, JavaScript buttons, delayed AJAX rendering and explicitly approved JSON POST. Verify actual rendered records and the independent classification/verification flow. Search completion or an HTTP response is not evidence that the objective is satisfied.

## Review hardening
The search scope now revalidates the input and exact query after asynchronous waits, re-resolves suggestion/button handles before clicking, excludes download and submitter override controls, and distinguishes nested result content from actual search chrome. Busy indicators and pending main-frame requests prevent a second submission while a debounced search is active. POST approvals require a literal boolean attestation; malformed URL-encoded bodies and duplicate keys are rejected. Expired or aborted scoped requests cannot leave a usable egress grant. Advanced search remains available for eligible queries even when general form input is enabled. The new delayed nested-results fixture is intended to catch false unchanged-page and duplicate-submission regressions.
