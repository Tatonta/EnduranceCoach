# Private backend pilot and verification

The backend-only container runs `app/platform` and the shared review engine. Its explicit copy allowlist excludes the personal Garmin client, `.env` files, data/catalogs, iOS fixtures and generated dependencies. It installs only `requirements-platform-runtime.txt` and runs as UID 10001 with bounded workers/connections and no health-related access logs.

No public hosting or domain is configured. This Compose stack is a **private, loopback-only pilot**, not an App Store backend environment.

## Start the pilot

Requires a working Linux Docker engine and Docker Compose. From the repository root:

```sh
python -m scripts.prepare_private_pilot
docker compose -f deploy/compose.yml up --build -d api
```

The helper creates random credentials under ignored `data/deployment`, prints no values and refuses to overwrite an existing setup. On Unix the directory is owner-only; read-only files can be mounted into the non-root container. On Windows restrict that directory's ACL to your own account before sharing the machine. Compose secrets are file mounts, not an encrypted vault; use the hosting provider's secret manager for production. See [Docker's secret handling](https://docs.docker.com/compose/how-tos/use-secrets/).

PostgreSQL 17 runs on a private network with a persistent named volume and no published host port. The one-shot initializer checks/creates schema revision 1; API workers start only after it succeeds. No private-data import or automatic schema upgrade happens. The API is at `http://127.0.0.1:8001`, registration is closed, and HTTPS is explicitly relaxed only for this private stack. Application defaults still require HTTPS.

The API joins a separate bridge network for its loopback host port and the internal database network. PostgreSQL and initialization remain only on the internal network. An API connected solely to an `internal: true` network cannot provide the intended host-facing ingress; this separation follows [Docker's Compose networking model](https://docs.docker.com/compose/how-tos/networking/).

For disposable coach test accounts, enable registration before starting the pilot:

```sh
COACH_PILOT_REGISTRATION=true docker compose -f deploy/compose.yml up --build -d api
python -m scripts.platform_smoke
```

In PowerShell set `$env:COACH_PILOT_REGISTRATION = 'true'`, then run the same Compose and smoke commands. The smoke script accepts loopback origins only and creates/deletes a random synthetic account. It checks readiness, login, plan write, empty review, activity import, last-workout advice and rejection of a premature adjustment, truthful vendor status, export and deletion. The imported workout is synthetic; this does not test watch connectivity. Restore the registration default after testing. A Debug iPhone simulator reaches localhost on its own Mac; physical devices need a reachable HTTPS service.

Stop without removing the database:

```sh
docker compose -f deploy/compose.yml down
```

Keep the secret files with that volume. Replacing a password file does not update a password in an initialized PostgreSQL database. Do not use `down --volumes` on an installation whose data you need to preserve; CI uses it only to remove its own disposable volume.

## Verification

- On 8 October 2026 all 31 API tests passed on real local PostgreSQL 17.11, with a unique database created and removed for each test. Coverage includes owner boundaries, duplicates, version conflicts, simultaneous acceptance, injected rollback, deletion and snapshot consistency.
- [Native CI run](https://github.com/Tatonta/EnduranceCoach/actions/runs/37741009818): Xcode 16.4 compiled the iOS app and all eight contract/transport tests passed. They do not authorize HealthKit or test device signing.
- `.github/workflows/backend.yml` repeats the full SQLite suite/lint, PostgreSQL API tests and a Linux container-stack smoke test. Inspect [GitHub Actions](https://github.com/Tatonta/EnduranceCoach/actions) for actual results; a workflow file alone is not passing evidence.
- Local Docker Desktop failed before starting its Linux engine because an inference-service socket was inaccessible. Tests used isolated PostgreSQL binaries instead; no Docker settings/data were reset. Local container runtime verification is unavailable until that engine works.

For PostgreSQL tests, set `COACH_TEST_POSTGRES_URL_FILE` to a private file containing a `postgresql+psycopg` URL for a dedicated **local** admin database, then run `python -m pytest tests/test_platform.py tests/test_platform_config.py -q`. The helper requires localhost/127.0.0.1 and a role permitted to create/drop databases. It removes only the random `coach_test_…` databases it created, never the supplied admin database. Omit the setting for SQLite tests. Do not test against a real deployment.

## Before public hosting

Provision hosting/domain and HTTPS. Keep workers behind the proxy, configure explicit allowed hosts, require HTTPS, and set `COACH_PLATFORM_TRUSTED_PROXIES` to only that proxy's addresses/CIDRs. The entry point rejects wildcard trust. Trusted forwarded headers must supply the HTTPS scheme and client IP; arbitrary client headers cannot be trusted. Separate runtime/migration database roles, configure database TLS and count connections across all replicas. The pilot's PostgreSQL role is for local testing only.

Public onboarding needs verified email/recovery, durable ingestion jobs, approved vendor OAuth connections, retention/erasure and operational monitoring. Use controlled migrations and restore-tested encrypted backups. [PostgreSQL pg_dump](https://www.postgresql.org/docs/17/app-pgdump.html) provides a consistent single-database backup, not a complete roles/cluster/PITR strategy. Signing, real-device QA and App Store submission remain separate gates in the [roadmap](../docs/PRODUCTION_ROADMAP.md).
