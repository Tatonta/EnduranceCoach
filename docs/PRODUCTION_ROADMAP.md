# Adaptive Coach: multi-vendor product and iOS release

Decision record, 5 October 2026. The current product is a local, single-athlete FastAPI application. It is not a hosted multi-user service or a submitted iOS app. Vendor access and platform requirements below were checked against official sources on this date.

Implementation update: a separate authenticated multi-athlete API now exists in `app/platform`, with database-backed plan versions, source-aware activity ingestion, owner-bound review/proposals, transactional acceptance, export and account deletion. See [PLATFORM_API.md](PLATFORM_API.md) for setup, the verified boundaries and remaining hosting gates. Native SwiftUI client source now exists in `ios`, including read-only HealthKit preview and explicit upload consent; see [iOS setup and verification](../ios/README.md). The personal dashboard remains local; the new API has not been publicly deployed and has no direct vendor connections. The native client compiled on the macOS CI runner and its eight contract/transport tests passed; device signing and real HealthKit/UI verification remain open. Developer enrollment and approved vendor API access are not configured.

## Delivered in this iteration

- `/review` contains Last workout and Practical advice tabs. Review is deterministic and explains available evidence and missing data.
- `/api/review/workout` gives mobile clients the same review as the web UI. Stored review snapshots include `workout_review`.
- Adjustment is offered only after four consecutive comparable easy runs over at least seven days, with a recent last run and recent synchronization. Each pace change must be at least 1%; total improvement must reach 6%, or slowing 8%. Heart rate, duration, source, activity type, hills and pauses must be comparable. These are transparent product heuristics, not scientifically validated fitness estimates.
- An improvement proposal adds 5% to explicitly easy timed running blocks. A deterioration proposal removes 15% from timed running/interval work blocks. Proposals cover tomorrow through the next seven days; distance-only blocks, rest, strength, warmup, cooldown, dates and pace targets are retained. Mixed timed/distance sessions can be only partially adjusted, as shown in the preview.
- The popup shows the proposed sessions and estimated durations. Accepting saves a backed-up local plan, clears existing test/cleanup proofs, and records the evidence. The same workouts cannot justify another increase or reduction. Garmin synchronization remains an explicit test-and-sync operation.
- Previews expire after ten minutes and are invalidated by plan, data, refresh, date or eligibility changes. GET review endpoints never refresh remote data or mutate a plan.
- `ActivityRecord` and `ActivitySource` define validated vendor-independent ingestion. Garmin now uses this boundary. Activities preserve source identity, aware timestamps and SI units. Non-Garmin activity IDs are namespaced. Service errors have a vendor-independent home in `app/errors.py`.
- `/api/integrations` distinguishes the implemented local adapter from planned integrations. No COROS, Suunto, Fitbit/Google Health, Amazfit, Xiaomi or HealthKit connection is advertised as working.

## Recommended product architecture

Keep this Python review engine and the new SwiftUI/HealthKit client source. Native review, advice, proposal acceptance, plan import, session handling, HealthKit import consent, export and deletion have been authored but have passed SDK compilation/contract tests and still need UI/real-device verification. The initial client keeps health responses only in memory and offers no offline adjustments or notifications. Preserve the web UI for diagnostics and desktop use.

Use a modular backend first, not premature microservices. Authentication, athlete plans, normalized ingestion and review/adaptation are now separated in the platform API. Every athlete request derives its owner from the server session. Provider connections and durable sync jobs are still missing. The personal dashboard's global `app.state.coach`, `user_id="local"`, JSON plan file, filesystem lock and shared token directory remain personal-only and must not be deployed as the public API.

Use PostgreSQL for athletes, plan versions, connections, activities, jobs, reviews, proposals and audit history. Every athlete-owned row needs an enforced athlete scope. Store plan application and its evidence/audit record in one transaction with optimistic version checks. The current local file/database workflow is serialized, but does not provide distributed transactions or production crash recovery across both stores.

Use a durable queue for refresh/backfill/webhook work, with per-connection serialization, retries, backoff, rate limits, idempotency keys and dead-letter handling. The current APScheduler and local file lock are for a single machine. A hosted service must schedule independently of an athlete's PC.

The platform persists unique `(athlete_id, provider, provider_activity_id)` records and conservatively groups near-exact duplicates across providers, preserving source references and stable review identity. Ambiguous duplicates remain separate. Provider revision/deletion markers, ingestion cursors and a user-facing uncertain-duplicate resolution flow remain future work. Source namespacing in the personal adapter alone is not duplicate detection.

Use OAuth authorization code flows, PKCE where supported, state validation, approved redirect URIs and least-privilege scopes. Encrypt provider tokens at rest under a managed key; handle refresh rotation, revocation and unlinking. Never ship vendor secrets inside the iOS binary. The current private Garmin session belongs to the local prototype.

Represent provider capabilities independently: activity read, detailed laps, physiology, webhook notifications, structured workout export and schedule export. Do not assume importing a workout implies the ability to send a training program back to that watch. Garmin sync, performances and climb analysis still depend on Garmin-specific detail/export APIs; the delivered boundary currently covers activity ingestion and review only.

## Integration sequence and dependencies

| Vendor | Production route | Current state / dependency |
| --- | --- | --- |
| Garmin | Official Connect Developer Program; Activity/Health and Training APIs as approved | Local adapter uses `python-garminconnect`. The official program is for business use and requires approval; its APIs use OAuth 2.0. Replace the personal session integration for production. See [Garmin program FAQ](https://developer.garmin.com/gc-developer-program/program-faq/). |
| Apple Health | Native HealthKit client with user authorization | Read-only importer source and explicit upload-consent preview are authored; macOS compilation/contract tests passed; HealthKit and real-device verification remain open. Useful as a bridge only where the vendor's app actually exports the required data. See [HealthKit](https://developer.apple.com/documentation/healthkit). |
| COROS | Approved developer application and OAuth integration | Obtain onboarding and documentation, then implement/test its adapter. See [COROS API application](https://support.coros.com/hc/en-us/articles/17085887816340-Submit-an-API-Application). |
| Suunto | Suunto partner program / Cloud API | Obtain partner acceptance and production access; support documented webhooks. See [Suunto APIZone](https://apizone.suunto.com/) and [FAQ](https://apizone.suunto.com/faq). |
| Fitbit / Google Health | Google Health API | Do not start a new legacy Fitbit integration: support ended 30 September 2026 and shutdown is scheduled for 30 October 2026. Google currently says it is not onboarding new projects. Access is an external dependency. See [official migration guide](https://developers.google.com/health/migration). |
| Amazfit / Zepp | Confirm approved cloud integration, or supported HealthKit bridge | Zepp OS device-app APIs and side services are a separate development route, not proof of unrestricted cloud history access. Verify devices and coverage before promising support. See [Zepp architecture](https://docs.zepp.com/docs/guides/architecture/arc/). |
| Xiaomi | Confirm vendor authorization and supported app/device/region, or verified HealthKit bridge | No verified, implemented cloud integration in this project. Keep unavailable until access and data coverage are tested. |

Start with Garmin and Apple Health, then one approved additional vendor. Build contract fixtures from authorized sample responses, test unit/timezone conversion, paging, missing fields, duplicates, deletion and token expiry, and pilot each integration before enabling it for everyone.

## Coaching quality before a public release

Collect explicit session exertion and next-day recovery reports with consent. Add lap-level compliance and sport-specific evidence, especially power for cycling. Keep a rule engine and evidence trail even if language-model wording is introduced. Insufficient data must continue to mean no adjustment proposal. Validate calibration, false-positive rates and user comprehension with a qualified coaching reviewer and a consenting pilot group. Thresholds need validation; similar heart rate is not proof that weather, route or recovery were comparable.

## iOS / App Store delivery gates

1. Extend the passing simulator build/contract tests with UI/device verification, replace the example bundle identifier, configure backend environments and create a signed build. An Apple Developer account and signing access are required for native release. A macOS CI build is now available; signing accounts and public hosting are not configured.
2. Verify the authored onboarding/login, permission explanations, native review/advice, explicit proposal acceptance, export and deletion flows. Direct-provider connection/unlink flows still need implementation after approval. The initial offline behavior retains only in-memory reference views and disables adjustments; there is no persistent health cache. Include useful native functionality rather than a thin website wrapper. See [App Review Guidelines](https://developer.apple.com/app-store/review/guidelines/), section 4.2.
3. Implement data export, retention, consent revocation and deletion. Apps offering account creation must let the user initiate account deletion within the app. See [Apple account-deletion guidance](https://developer.apple.com/help/app-review/guideline-reference/5-1-1-account-deletion/).
4. Complete privacy policy and App Store privacy disclosures for the data actually collected, including provider and third-party services. Apply Apple's health/fitness-data rules, including restrictions on advertising/data mining and health-data storage. See [App Review Guidelines](https://developer.apple.com/app-store/review/guidelines/), sections 5.1.1 and 5.1.3. Obtain appropriate review for the intended launch regions rather than assuming the private prototype's consent model is enough.
5. Resolve commercial data rights. The bundled local Climbfinder catalog is documented as private personal-use data; it is not a production-licensed catalog. Keep it out of distributed builds until rights are established or use a licensed alternative.
6. Test real permission denial/revocation, offline use, duplicate imports, provider failures, timezone travel and restored sessions. Use TestFlight with consenting testers and monitor failed jobs without logging tokens or private workout routes.
7. Prepare screenshots, descriptions, support/privacy URLs, review instructions and a working demo account or demo mode. Apple requires complete review access and disclosure of external services/hardware. See [complete-review guidance](https://developer.apple.com/help/app-review/before-submitting-for-review/complete-review/).
8. Submit the signed release through App Store Connect after the above gates pass. Developer/vendor approvals, contracts and store review cannot be completed by code changes alone.

## Acceptance milestones

| Milestone | Evidence required |
| --- | --- |
| Local review feature | Automated conservative-trend and preview tests; browser review/advice checks with real cached data and isolated test proposals |
| Hosted pilot | Account/API isolation, transactional plans/proposals and export/deletion are implemented and tested locally. Still needs encrypted per-user vendor connections, durable jobs, PostgreSQL runtime/load verification, public account lifecycle, restore exercises and deployment observability. |
| Multi-vendor pilot | At least two real approved vendor integrations; canonical contract fixtures; deduplication and failure/revocation tests |
| iOS beta | Signed build; working permission/onboarding/review flows on real hardware; TestFlight pilot |
| App Store release | Privacy/data-rights gates, review materials and Apple approval |
