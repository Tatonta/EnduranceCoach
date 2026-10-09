# Native Adaptive Coach client

SwiftUI iPhone app, iOS 17+, no third-party SDKs. Open **AdaptiveCoach.xcodeproj** on a Mac with Xcode 16 or newer. The latest application code (`3270a38`) compiled and passed **25 native contract tests and two UI flows** on 9 October 2026 in [this macOS run](https://github.com/Tatonta/EnduranceCoach/actions/runs/37943861538). Unit tests use an unsigned simulator build; UI tests use local ad hoc simulator signing. The experimental ChatGPT flow still needs real account/iPhone verification. This is not a signed or verified App Store release. Source is public under MIT on [develop](https://github.com/Tatonta/EnduranceCoach/tree/develop). Local SDK compilation is unavailable on the Windows development host.

## Implemented flows

- On-demand HealthKit detail preview for a selected running/cycling workout: associated quantity samples, dynamics, explicit lap/segment events and optional route reading. Detail and GPS upload consent are separate; summary/detail writes are bound by the source hash returned by import. Device and permission verification remain open. See [HealthKit detailed flow](../docs/HEALTHKIT_DETAILS.md).

- Detailed native review when the backend has canonical evidence: phase targets from a referenced plan version, lap metrics, running dynamics, separate pace/HR charts and GPS segments in MapKit. Missing/stale details remain explicit. The HealthKit importer can supply selected associated details with separate consent; coverage must still be verified on a real device and does not establish live access from every vendor. See [canonical detailed-evidence contract](../docs/CANONICAL_DETAILS.md).

- Manual session recording from Coach, including optional distance/exertion, feelings, discomfort and notes. It requires no HealthKit permission and labels the evidence as self-reported. The same request identity is retained after a failed save. Recent manual feedback appears in Coach and Review; missing distance is shown as unknown. See [manual feedback contract](../docs/MANUAL_FEEDBACK.md).

- First authenticated access opens a five-step coaching questionnaire. Goal/deadline, device or no device, optional age/weight/height, running/cycling history, recent volume, best performances, gym and weekly availability are saved to the authenticated athlete profile. Coach is the first tab; the profile can be edited later. Questionnaire submission does not change an existing plan or request HealthKit access. The native client now has an experimental direct ChatGPT OAuth and review flow, with separate sharing consent; real iPhone/account verification remains open. The personal local version implements conversation and initial drafts. See [native ChatGPT boundary](../docs/NATIVE_CHATGPT.md).

- Separate Review and Advice tabs, metrics with missing values shown explicitly, server explanations and supporting trend evidence.
- Optional adjustment sheet appears only when a successful recent review is eligible. Before opening it, the client refreshes evidence and requests a server-owned proposal. The sheet shows every changed work block, duration and repeat count. Acceptance requires a confirmation toggle. Expired previews and stale evidence cannot apply; the API rechecks ownership and versions atomically. Watch export is clearly unavailable.
- Login/optional registration against a configurable HTTPS origin. Registration is closed unless the operator enables it. Passwords are never persisted. Bearer sessions use Keychain `WhenUnlockedThisDeviceOnly` and are bound to the origin and account. Redirects are rejected. Logout revokes the server session where reachable and clears local state; the app states when remote revocation was not confirmed.
- Plan JSON import with preview, explicit acceptance and optimistic version checks. The complete plan, including case-sensitive arbitrary athlete metadata, is preserved. The server performs authoritative validation. This version does not have a program-generation wizard.
- Optional, read-only HealthKit import of the last 42 days, capped at 500 workouts. Exceeding that limit aborts the import rather than silently truncating history. Stable HealthKit workout UUIDs support idempotent imports. Only workout-associated HR samples are used; absent HR/ascent remain absent. No attempt is made to infer easy effort from pace. The user can give an accurate session name in the preview.
- A separate upload-consent toggle identifies the destination and signed-in account. Nothing is uploaded just because HealthKit authorization completed. There is no background import, continuous sync, HealthKit write or vendor credential collection. Optional GPS-route reading and upload have separate explicit choices.
- Account data export through the iOS share sheet and password-confirmed account deletion. Export files are protected, excluded from backup, removed after sharing/logout, and cleaned on the next launch after an interruption. Deletion removes account data from the coaching service, preserving original HealthKit records.
- Workout responses remain in memory; there is no offline health-data cache. A failed request or background transition invalidates adjustment availability. The inactive screen is covered to limit app-switcher exposure. It does not prevent user screenshots while active.

Apple does not reveal read-permission denial to an app. An empty HealthKit result says no readable workouts, and does not falsely claim a connected/authorized watch. See [HealthKit authorization](https://developer.apple.com/documentation/healthkit/authorizing-access-to-health-data). A vendor app writing to Apple Health is a bridge, not a direct vendor API connection, and completeness must be tested per device/app/region.

## Run on a Mac

1. Open `AdaptiveCoach.xcodeproj`, select the **AdaptiveCoach** scheme and an iPhone simulator. Run tests with Product → Test. For device builds, select your signing team, replace the example bundle identifiers and provision the HealthKit capability.
2. Install/start the **separate platform API**, not the personal port-8000 Garmin dashboard. See [platform setup](../docs/PLATFORM_API.md). Use a dedicated test database and enable registration for your private pilot only.
3. Start that API on the **Mac** at port 8001. In a Debug simulator build, the service-origin field accepts `http://localhost:8001`. A simulator's loopback is the Mac; it cannot reach a backend on this Windows PC through localhost. Physical-device and Release builds require a reachable HTTPS origin allowed by the backend's host configuration. No general ATS bypass is configured.
4. Create a test account, import a validated program JSON from Files, then prepare and consent to a HealthKit import. Simulator HealthKit may have no data; use a real device for permission and data-coverage testing.

The synthetic plan at `AdaptiveCoachTests/Fixtures/plan.json` is an **API response wrapper**. To test import, save its `plan` object as a separate JSON file. It is a decoder fixture with fixed 2026 dates, not personal training advice. Never use personal Garmin files or tokens as bundled demo data.

CLI testing after selecting a currently installed simulator:

```sh
xcrun simctl list devices available
xcodebuild test -project ios/AdaptiveCoach.xcodeproj -scheme AdaptiveCoach \
  -destination 'platform=iOS Simulator,name=<installed iPhone simulator name>' \
  -derivedDataPath ios/DerivedData CODE_SIGNING_ALLOWED=YES CODE_SIGNING_REQUIRED=YES CODE_SIGN_IDENTITY=-
```

The included `.github/workflows/ios.yml` runs this on a macOS runner for relevant pushes/pull requests and manual dispatches. It builds/tests without publishing or signing a release. Its presence is not a passing CI result.

## Fixtures and project regeneration

From the repository root, in a Python environment with `.[platform,dev]` installed:

```sh
python -m scripts.create_ios_contract_fixtures
python -m scripts.create_ios_project
```

The first command uses an isolated temporary database and the real authenticated API. It exercises empty review, Apple Health-shaped import, eligibility, proposal, acceptance and evidence consumption. No real account, token, private activity or Garmin plan is bundled. Native `ContractTests.swift` decodes these responses, checks wire names and metadata preservation, and exercises transport/conflict handling via an isolated URLProtocol fixture. These XCTest cases passed in macOS CI; they do not authorize HealthKit or verify real-device coverage. The project generator has deterministic object IDs; regeneration replaces hand-edited project settings, so update the generator when changing settings or files.

Project regeneration is deterministic and retains separate unit and UI test schemes. macOS CI supplies SDK compilation; local parsing or project generation on Windows does not prove Swift types, permission behavior or signing.

## Release gates still open

- Extend the passing macOS contract tests with UI and real-device QA: VoiceOver, Dynamic Type, light/dark, navigation, errors, interrupted operations, permission denial/revocation, locked HealthKit, missing HR/ascent, timezone changes, duplicate sources, repeated imports, offline restore, account deletion and export cleanup.
- A reachable hosted PostgreSQL service, account verification/recovery, restore-tested backups, retention/revocation policies and appropriate observability. See [production roadmap](../docs/PRODUCTION_ROADMAP.md).
- Apple Developer enrollment and signed TestFlight builds. Developer signing and approved vendor API accounts are not configured. There are no direct vendor APIs or production credentials in this client.
- App identity, reviewed icon/branding, privacy/support URLs, accessibility and localization review, reviewed App Store privacy disclosures, licensed content, coaching validation and review access. `PrivacyInfo.xcprivacy` describes the current code's health/fitness, account and uploaded-plan collection, with no tracking; it must be checked against the eventual hosting, logs, support and any added SDKs. It is not a legal policy or a completed App Store disclosure. See [Apple privacy-manifest guidance](https://developer.apple.com/documentation/bundleresources/describing-data-use-in-privacy-manifests).
- Official provider approvals, OAuth callbacks/token lifecycle, durable jobs and verified data coverage before any vendor is advertised as connected. The original personal Garmin adapter is not part of this iOS app or the platform API.

Nothing has been submitted or published to the App Store.

La review canonica e i controlli contestuali hanno passato build, 17 test di contratto e due flussi UI in [questa verifica macOS](https://github.com/Tatonta/EnduranceCoach/actions/runs/37902116734). La prova è nel simulatore, senza firma per la distribuzione o verifica su dispositivo reale.

## Native UI flows against a disposable backend

The separate **AdaptiveCoachUI** scheme runs two XCUITest flows against the real authenticated platform API, using a new temporary SQLite database and generated test-only access. The first starts without a profile, completes the five-step questionnaire, reads the workout, opens a proposal, checks that acceptance is disabled without confirmation, accepts and verifies plan version 2. The second uses two laps at 120/160 bpm with a whole-workout mean of 140 and verifies that the proposal stays hidden. Screenshots are retained in the UI result bundle. These flows do not request HealthKit access or contact watch vendors or OpenAI.

The UI build uses local ad hoc simulator signing so Keychain session storage works. This is not an Apple Developer certificate or an App Store signing identity. The macOS workflow starts the fixture backend on loopback and passes its generated access to the test runner via `TEST_RUNNER_COACH_UI_TEST_PASSWORD` and `TEST_RUNNER_COACH_UI_TEST_ORIGIN`. The credential file remains outside the checkout and is not an artifact. UI tests require a fresh simulator with no existing athlete session. They fail if access is absent; they do not silently skip. The default **AdaptiveCoach** scheme continues to run the contract tests without needing this server.

For a local Mac run, start `python -m scripts.ios_ui_backend --directory <new-empty-temporary-directory> --port 8001`, pass the access file values through those runner environment variables, and run `xcodebuild test` using the AdaptiveCoachUI scheme and a fresh simulator. Never point this workflow at a real account or an existing deployment database. An existing directory with contents is refused.

Both UI flows passed on commit `9718efdeb90c3979998896cbd981e39a4f675d8a` in the linked macOS run. This establishes simulator UI behavior. Real-device permissions, a signed distribution build and App Store submission remain open.

## Experimental direct ChatGPT review

The Coach tab exposes Continue with ChatGPT, a first-use plan notice, an account-specific model picker and per-request sharing consent. OAuth tokens stay in the device Keychain, bound to the backend origin and athlete. Profile, bounded history and measured detail evidence come from `/v1/coach/context`; GPS routes and credentials are excluded. The response cannot change the training plan. Sign-out from EnduranceCoach stops local requests and retains the encrypted, owner-bound ChatGPT registration for that same athlete; Scollega ChatGPT clears the tokens and attempts remote revocation. Account deletion also removes that registration.

The app is free/open source; an eligible ChatGPT plan and OpenAI availability still apply. No API-key fallback or backend token proxy is included. The loopback callback inside the system authentication browser is an implementation that must be tested on an actual iPhone against OpenAI. Synthetic XCTest and UI checks do not prove real OAuth/inference, App Store acceptance or coaching quality. The privacy manifest covers health/fitness and user content, but direct transmission to OpenAI must also appear in the eventual consent/privacy policy and reviewed App Store disclosures.

## Account registry and Keychain checks

The ChatGPT picker keeps separate issued-client registrations, including accounts/workspaces with the same email. Switching requires a newly verified OAuth result. Pending registration IDs survive failed code exchange; signed-out registrations retain their stable label and identity. The old single-account record migrates only after a protected replacement is saved. Account deletion attempts revocation of all saved renewable sessions.

The contract suite now includes actual simulator Keychain round trips, owner isolation, legacy migration and removal of all credential formats. These tests use random test-owned binding keys and synthetic credentials, and clear only those keys. Run the unit scheme with local ad hoc simulator signing, as in the command above; unsigned tests cannot access the Keychain. This needs no developer certificate and supplies no real-device or live-OpenAI verification.
