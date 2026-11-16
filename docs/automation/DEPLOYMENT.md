# Deployment and operations

These are repository deployment instructions, not evidence that an external production stack has been
changed. Defaults preserve existing automatic workflows; new rotation/failover capabilities require
explicit operator policy. Pause current automation before rollout when your environment requires it.

## Prepare and migrate

1. Back up PostgreSQL consistently, artifacts, private proxy configuration and encryption keys using
   the existing hosting/database backup service. Record its schedule, retention, access controls and
   restore location. This repository has no connected backup provider to configure automatically.
2. Restore that backup into an isolated database/environment. Verify website/job/event counts, content
   published/draft revisions, User-Agent settings and the ability to decrypt a known test session. Never
   run browser jobs against live third-party destinations during a restore drill. Record restore time
   and recovery-point evidence in your deployment record.
3. Build the reviewed code and install selected browser binaries. Preserve private environment settings.
   Production requires PostgreSQL, Redis, non-fixture mode and explicit authorized domains/hosts.
4. Run from `backend`: `python -m alembic upgrade head`, then `python -m alembic check`.
   New revision: `a20d00000001`, after `f19c00000001`. It retains existing job/frontier/event history;
   SQLite uses native column additions to avoid cascading child-table data loss during batch recreation.
5. Deploy matching API, worker and scheduler versions together; retain one logical scheduler service.
   Multiple workers share SQL selection, job/slot/domain leases and proxy cooldown state.

## Start and verify

Existing commands remain `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
--no-proxy-headers --no-server-header --no-access-log`, `python -m app.worker` and
`python -m app.scheduler`. In Windows development use `..\.venv\Scripts\python.exe` from `backend`.
Production should use the provided containers/hosting supervisor, not an interactive terminal.

Compose backend services use `init:true`, `restart:on-failure:5` and JSON log size retention (10 MB,
three files per backend container). Worker stop grace is 20 seconds; browser close is bounded at ten
seconds. Configure host health alerts and supervisor behavior for sustained failures; Compose alone
does not restart a living unhealthy container. Host log collectors need their own retention policy.

Check `/api/health`, `/api/ready`, authenticated Automation heartbeats and network diagnostics. Verify a
released read-only fixture/integration job end to end, then safe pause/resume/cancellation and recovery.
Check approved schedules and destination rate limits. Review load/resource limits before scaling.
Synchronize worker clocks. Give services the existing least-privilege DB/network permissions.

## Rollback

Pause intake, stop workers/scheduler, inspect outstanding actions and take a fresh backup. Prefer rolling
back code/configuration to a compatible release while retaining the additive schema. Export policy
history and assignments before `alembic downgrade f19c00000001`: downgrade drops all six automation
tables and priority/dependency/manual-release fields, including their operational audit. It does not
undo external effects. Verify content/User-Agent/job history and readiness after any rollback.

## External operator requirements

Provision and verify real proxy allocation, credentials, CA trust, owned health URLs and allowed CONNECT
ports. Configure hosting process/container supervision, persistent storage, host resource/disk alerts,
off-host backups and an isolated restore drill. Verify PostgreSQL/Redis behavior under multi-host load.
Validate TLS, DNS, Cloudflare Tunnel/account setup, explicit proxy trust, direct-origin rejection and
host egress firewall controls using the existing [network requirements](../security/EXTERNAL_NETWORK_REQUIREMENTS.md).
No Cloudflare account, DNS, firewall, hosting or live proxy changes are performed by repository edits.

Local fixture tests do not certify production, authenticated external integrations or live AI providers.
