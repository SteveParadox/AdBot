# User-Agent validation and authorization

Accept arbitrary identifiers without a browser whitelist. Preserve exactly; no trimming or rewriting.
Values must be nonempty printable ASCII (0x20..0x7e), no leading/trailing whitespace and within the
operator length limit (default 512). CR/LF, NUL, TAB, DEL and non-ASCII are rejected. ASCII is the common
safe subset for the actual HTTPX/browser transports; Unicode is not silently transcoded. Length is
bounded on input and selection. IDs have a restricted identifier syntax; display fields render as React
text. APIs reject extra fields, duplicate IDs, unknown services and missing profile references.

Admin APIs reuse workspace bearer authentication, content-admin allowlisting, ingress/key rate limits,
CORS, safe validation errors and no-store headers. They never accept untrusted per-request overrides.
There are no authentication cookies to introduce a CSRF cookie flow. Profiles/config are global, so
administrator grants are global as with public content. Configuration/audit records commit together;
revision CAS prevents lost writes. Audit stores administrator hash, revision and timestamp, not header
strings, proxy credentials or payloads. DB singleton/revision constraints complement application checks.

Fixed provider identity comes from operator configuration and takes precedence over manual/per-request
choices. Read validation and dispatch validation protect against corrupt stored values. Missing config
uses a safe default; malformed persisted config fails closed. Operator capability changes require restart;
review saved rotation policies before removing permission to avoid intentionally fail-closed reads.
Do not store passwords/tokens in UA strings: the header is deliberately sent to the destination and can
appear in its logs. Admin previews are private, but arbitrary configured strings are not secret storage.

Run tests and stage migrations/proxy flows before production deployment. Local tests do not verify real
provider identity contracts, fixed exit allocation, Cloudflare/TLS/origin restrictions or host firewalls.
