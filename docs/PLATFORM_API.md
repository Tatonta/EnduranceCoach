# Authenticated multi-athlete backend

This is the implemented account/API portion of the production roadmap. It runs separately from the personal Garmin dashboard. It reuses the review engine, but stores athlete plans, activity sources and adaptation history in database transactions. It does not log in to the personal Garmin account or read the local plan, private climb catalog or token directory.

A native SwiftUI client targeting this API is authored in `ios/AdaptiveCoach.xcodeproj`. It includes Review/Advice, explicit proposal acceptance, plan import, an optional read-only Apple Health preview with separate upload consent, Keychain sessions, export and deletion. See [native setup and verification limits](../ios/README.md). The iOS source compiled and passed eight contract/transport tests in macOS CI; this does not establish live vendor connections, HealthKit/device verification or hosted deployment.

## Local setup

From the project directory, install the optional dependencies and initialize the new database explicitly:

```powershell
.venv\Scripts\python.exe -m pip install -e ".[dev,platform]" -c requirements-lock.txt -c requirements-platform-lock.txt
.venv\Scripts\python.exe -m app.platform.cli init-db
```

The default database is `data/platform/coach.sqlite3`, ignored by Git. The initializer refuses the personal `data/coach.sqlite3` database. It creates schema revision 2 or explicitly upgrades revision 1 by adding the athlete-profile table without replacing existing data. Re-running the initializer is harmless on revision 2; unknown revisions and incomplete schemas fail closed. API startup only checks the revision. Back up an existing deployment before running the initializer.

For a **local, loopback-only pilot** you may enable registration and plain HTTP in that terminal:

```powershell
$env:COACH_PLATFORM_REQUIRE_HTTPS = "false"
$env:COACH_PLATFORM_REGISTRATION = "true"
.venv\Scripts\python.exe -m app.platform.cli serve --port 8001
```

The CLI binds to `127.0.0.1`; it does not publish the service. The standard defaults require HTTPS and disable registration. Restore those defaults for hosting. `config/platform-environment.example` documents configuration but is not loaded automatically. The local personal app stays at port 8000.

Generate the mobile API contract without creating accounts or accessing private data:

```powershell
.venv\Scripts\python.exe -m app.platform.cli schema > docs\platform-openapi.json
```

Interactive Swagger/Redoc are disabled on the platform service. Signed-in clients can read `/v1/openapi.json`.

## Account flow

1. `POST /v1/auth/register` with `email`, a 12–128 character `password`, and an optional IANA `timezone`. Registration is available only when explicitly enabled. Do not use the actual watch-account password as the coach account password.
2. `POST /v1/auth/login` with email/password. The response contains an opaque bearer token and expiry. Passwords are hashed with Argon2id; only token digests are stored. Defaults expire sessions after 24 hours.
3. Send `Authorization: Bearer <token>` on athlete routes. The authenticated session determines the athlete; requests cannot choose another athlete ID.
4. `POST /v1/auth/logout` revokes the current session. Expired or revoked sessions return 401.

Account and client-IP login limits live in the database, so multiple application processes do not each get a separate allowance. API validation failures never echo supplied password values or activity payloads. Responses containing account data are marked `Cache-Control: no-store`.

These are pilot account flows. Public onboarding still needs verified-email enrollment, account recovery, delivery-provider configuration, monitoring and review of abuse controls. Signup is therefore closed by default. Database credential provisioning, MFA/SSO if chosen, and production operation are not inferred to be complete.

## Implemented contract

| Endpoint | Behavior |
| --- | --- |
| `GET /health` | Schema/readiness status only; no athlete data |
| `GET /v1/me` | Signed-in athlete identity and timezone |
| `GET/PUT /v1/profile` | Owner-bound coaching questionnaire, independent of the program; PUT requires `expected_version`, stale writes return 409 |
| `GET /v1/me/export` | Own account, all plan versions, original imported activity sources, proposals, adjustment evidence and audit history; no password/session secrets |
| `DELETE /v1/me` | Own account deletion; requires current password and `confirmed: true`; related data and all sessions cascade-delete in the same transaction |
| `GET /v1/plan` | Current own plan and version, or 404 before creation |
| `PUT /v1/plan` | Validated plan plus `expected_version`; 0 creates the first plan; stale writers receive 409 |
| `GET /v1/plan/history` | Own immutable previous plan versions |
| `POST /v1/activities/import` | Batch of 1–500 canonical `ActivityRecord` objects, explicitly marked `client_import` |
| `POST /v1/activities/manual` | Own concluded, self-reported session and feedback; requires a saved profile; stable request UUID makes repeated saves idempotent |
| `GET /v1/activities?limit=50&offset=0` | Own canonical workouts with source references, total and next offset; maximum page size 200 |
| `DELETE /v1/activities/{provider}/{provider_id}` | Remove only that source record from the signed-in athlete |
| `GET /v1/review/workout` | Shared review/advice engine, current plan version and interpretation limits |
| `POST /v1/review/adjustments/preview` | Optional ten-minute proposal, only when the trend is eligible |
| `POST /v1/review/adjustments/{proposal_id}/apply` | Owner-bound proposal, explicit confirmation and expected version; transactional plan/evidence/audit update |
| `GET /v1/integrations` | Lists vendor targets truthfully: no live platform connections yet |
| `GET /v1/openapi.json` | Authenticated schema for native/client development |

A plan write includes the expected version and uses the existing validated Plan schema. Example valid creation:

```json
{
  "expected_version": 0,
  "plan": {
    "plan_name": "Easy build",
    "workouts": [{
      "id": "easy-01", "date": "2026-10-06", "name": "Easy run", "sport": "running",
      "estimated_duration_min": 40,
      "steps": [{"type": "warmup", "duration_min": 10}, {"type": "run", "duration_min": 25}, {"type": "cooldown", "duration_min": 5}]
    }]
  }
}
```

## Ingestion and duplicates

Source IDs are unique per athlete/provider. Re-importing one source record updates it without creating another workout. Timestamps require an offset; SI units and finite nonnegative metrics are validated before a batch can write anything. A future activity or repeated source identity rejects the entire batch.

The same event from different providers is automatically linked only when sport, start time (within two seconds), duration (within one second) and distance (within one metre) agree. Candidate groups must contain one record per provider and every pair must match. Ambiguous multiple matches and transitive time chains are retained separately. This intentionally narrow deduplication is incomplete for provider exports that round or truncate records; a future explicit user-resolution flow is still needed.

Every canonical workout retains original source references and import provenance. Canonical IDs remain stable when a matching provider is added. Materially divergent updates split a linked source rather than silently changing every provider's record. Duplicate searches use an athlete/time index; they do not compare all pairs across the entire lifetime history. Review reads only the required plan/42-day window and refuses to make a proposal if coverage exceeds its 2,000-workout processing bound.

Client imports are supplied by the signed-in athlete and are not verified vendor-API data. The API does not advertise a live connection or send workouts to a watch. An authorized HealthKit client or future vendor worker can map its data to the same schema once implemented.

## Atomic adaptation and privacy

Mutations lock the athlete row through an actual database update. This serializes plan edits, imports and acceptance across workers without a machine-local file lock. A proposal is checked against owner, status, expiry, current plan version and the current evidence hash inside that transaction. Plan version, consumed evidence and audit event all commit together; failures roll back everything. The current local dashboard's file/SQLite coordination is separate and is not used by this backend.

Password-confirmed account deletion removes athlete data and active sessions through database foreign-key cascades. Export contains the data needed to explain decisions, including source records and previous plans. Rate-limit records contain digests only and expire; deployment backup retention and erasure procedures still need an operational policy.

## PostgreSQL hosting and remaining gates

Set `COACH_PLATFORM_DATABASE_URL` to a `postgresql+psycopg://` DSN provisioned securely outside source control. Use managed TLS options appropriate to that database, an explicit `COACH_PLATFORM_ALLOWED_HOSTS`, HTTPS termination and trusted proxy settings. Run the schema initializer as a controlled deployment operation before starting application workers. Do not deploy `app.main:app`, whose routes are intentionally local and unauthenticated.

The same 31 API integration tests passed against real PostgreSQL 17.11 on 8 October 2026, using a disposable local server and a separate database for each test. Coverage includes account isolation, source ingestion/deduplication, optimistic plan versions, competing proposal acceptance, transaction rollback, export/deletion and consistent read snapshots while another worker commits. These results verify those database behaviors; they do not prove public hosting, a load target, backup recovery or live vendor connections.

Read endpoints use repeatable snapshots so plan, activity and adaptation queries cannot mix different committed moments. Writes retain the athlete lock and PostgreSQL's read-committed semantics. PostgreSQL pools are bounded per worker (default five connections plus five overflow), with connect, statement, lock and idle-transaction timeouts. Configure `COACH_PLATFORM_POOL_SIZE`, `COACH_PLATFORM_POOL_OVERFLOW`, `COACH_PLATFORM_DB_CONNECT_TIMEOUT`, `COACH_PLATFORM_DB_STATEMENT_TIMEOUT_MS` and `COACH_PLATFORM_DB_LOCK_TIMEOUT_MS` for the deployment's connection budget; count every worker and replica.

Database URLs may instead be supplied through `COACH_PLATFORM_DATABASE_URL_FILE` as a mounted secret. Configuring both forms is rejected, empty/oversized secret files fail closed, and settings representations omit the DSN. Platform configuration does not import the personal app's `.env` loader. Invalid boolean values cannot silently disable HTTPS.

For a repeatable local container pilot and CI verification, see [deployment guide](../deploy/README.md). The container copies only platform and shared review-engine source; personal Garmin modules, sessions, data and private assets are excluded. The pilot binds HTTP only to loopback, keeps PostgreSQL unexposed, runs the API as UID 10001 and initializes schema before workers start. It is a private pilot configuration, not an internet deployment.

Before the hosted pilot, add durable sync jobs/webhooks, encrypted per-user OAuth connections, real approved provider adapters, account verification/recovery, deployment migrations for later schema revisions, metrics, backup/restore exercises and PostgreSQL integration/load testing. Before the App Store milestone, build and validate the native iOS client and meet the remaining gates in [PRODUCTION_ROADMAP.md](PRODUCTION_ROADMAP.md).
