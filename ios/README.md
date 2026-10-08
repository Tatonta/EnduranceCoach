# Native Adaptive Coach client

SwiftUI iPhone app, iOS 17+, no third-party SDKs. Open **AdaptiveCoach.xcodeproj** on a Mac with Xcode 16 or newer. Xcode 16.4 compiled the app and all eight native contract/transport tests passed on 8 October 2026 in [this macOS CI run](https://github.com/Tatonta/EnduranceCoach/actions/runs/37741009818). This is an unsigned simulator build, not a signed or verified App Store release: the development host is Windows and has neither Swift nor Xcode. The source is hosted on [Tatonta/EnduranceCoach, develop](https://github.com/Tatonta/EnduranceCoach/tree/develop). Check [GitHub Actions](https://github.com/Tatonta/EnduranceCoach/actions) for the current macOS build status; local SDK compilation is unavailable on Windows.

## Implemented flows

- First authenticated access opens a five-step coaching questionnaire. Goal/deadline, device or no device, optional age/weight/height, running/cycling history, recent volume, best performances, gym and weekly availability are saved to the authenticated athlete profile. Coach is the first tab; the profile can be edited later. Questionnaire submission does not change an existing plan or request HealthKit access. The remote ChatGPT integration remains an external availability gate; the personal local version implements the conversation and initial draft.

- Separate Review and Advice tabs, metrics with missing values shown explicitly, server explanations and supporting trend evidence.
- Optional adjustment sheet appears only when a successful recent review is eligible. Before opening it, the client refreshes evidence and requests a server-owned proposal. The sheet shows every changed work block, duration and repeat count. Acceptance requires a confirmation toggle. Expired previews and stale evidence cannot apply; the API rechecks ownership and versions atomically. Watch export is clearly unavailable.
- Login/optional registration against a configurable HTTPS origin. Registration is closed unless the operator enables it. Passwords are never persisted. Bearer sessions use Keychain `WhenUnlockedThisDeviceOnly` and are bound to the origin and account. Redirects are rejected. Logout revokes the server session where reachable and clears local state; the app states when remote revocation was not confirmed.
- Plan JSON import with preview, explicit acceptance and optimistic version checks. The complete plan, including case-sensitive arbitrary athlete metadata, is preserved. The server performs authoritative validation. This version does not have a program-generation wizard.
- Optional, read-only HealthKit import of the last 42 days, capped at 500 workouts. Exceeding that limit aborts the import rather than silently truncating history. Stable HealthKit workout UUIDs support idempotent imports. Only workout-associated HR samples are used; absent HR/ascent remain absent. No attempt is made to infer easy effort from pace. The user can give an accurate session name in the preview.
- A separate upload-consent toggle identifies the destination and signed-in account. Nothing is uploaded just because HealthKit authorization completed. No background import, continuous sync, HealthKit write, GPS-route read or vendor credential collection.
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
  -derivedDataPath ios/DerivedData CODE_SIGNING_ALLOWED=NO
```

The included `.github/workflows/ios.yml` runs this on a macOS runner for relevant pushes/pull requests and manual dispatches. It builds/tests without publishing or signing a release. Its presence is not a passing CI result.

## Fixtures and project regeneration

From the repository root, in a Python environment with `.[platform,dev]` installed:

```sh
python -m scripts.create_ios_contract_fixtures
python -m scripts.create_ios_project
```

The first command uses an isolated temporary database and the real authenticated API. It exercises empty review, Apple Health-shaped import, eligibility, proposal, acceptance and evidence consumption. No real account, token, private activity or Garmin plan is bundled. Native `ContractTests.swift` decodes these responses, checks wire names and metadata preservation, and exercises transport/conflict handling via an isolated URLProtocol fixture. These XCTest cases passed in macOS CI; they do not authorize HealthKit or verify real-device coverage. The project generator has deterministic object IDs; regeneration replaces hand-edited project settings, so update the generator when changing settings or files.

Locally verified on Windows: all 10 Swift files parse with the tree-sitter Swift grammar; all project object references resolve with an OpenStep parser; Info.plist, entitlements and privacy manifest parse; the eight contract fixtures were produced through successful real API operations. Syntax parsing cannot verify Swift types, Apple SDK availability, entitlement provisioning or SwiftUI/HealthKit runtime behavior.

## Release gates still open

- Extend the passing macOS contract tests with UI and real-device QA: VoiceOver, Dynamic Type, light/dark, navigation, errors, interrupted operations, permission denial/revocation, locked HealthKit, missing HR/ascent, timezone changes, duplicate sources, repeated imports, offline restore, account deletion and export cleanup.
- A reachable hosted PostgreSQL service, account verification/recovery, restore-tested backups, retention/revocation policies and appropriate observability. See [production roadmap](../docs/PRODUCTION_ROADMAP.md).
- Apple Developer enrollment and signed TestFlight builds. Developer signing and approved vendor API accounts are not configured. There are no direct vendor APIs or production credentials in this client.
- App identity, reviewed icon/branding, privacy/support URLs, accessibility and localization review, reviewed App Store privacy disclosures, licensed content, coaching validation and review access. `PrivacyInfo.xcprivacy` describes the current code's health/fitness, account and uploaded-plan collection, with no tracking; it must be checked against the eventual hosting, logs, support and any added SDKs. It is not a legal policy or a completed App Store disclosure. See [Apple privacy-manifest guidance](https://developer.apple.com/documentation/bundleresources/describing-data-use-in-privacy-manifests).
- Official provider approvals, OAuth callbacks/token lifecycle, durable jobs and verified data coverage before any vendor is advertised as connected. The original personal Garmin adapter is not part of this iOS app or the platform API.

Nothing has been submitted or published to the App Store.
