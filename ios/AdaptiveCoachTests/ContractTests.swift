import XCTest
import Security
@testable import AdaptiveCoach

final class ContractTests: XCTestCase {
    private func data(_ name: String) throws -> Data {
        let url = try XCTUnwrap(Bundle(for: Self.self).url(forResource: name, withExtension: "json", subdirectory: "Fixtures"))
        return try Data(contentsOf: url)
    }
    func testReviewEmptyAndMissingMetricsDecode() throws {
        let empty = try Wire.decoder().decode(WorkoutReview.self, from: data("review-empty"))
        XCTAssertNil(empty.lastWorkout)
        XCTAssertFalse(empty.program.eligible)
        var payload = try XCTUnwrap(JSONSerialization.jsonObject(with: data("review-improving")) as? [String: Any])
        var workout = try XCTUnwrap(payload["last_workout"] as? [String: Any])
        for key in ["avg_hr", "avg_pace_s_km", "elevation_gain_m"] { workout[key] = NSNull() }
        payload["last_workout"] = workout
        let review = try Wire.decoder().decode(WorkoutReview.self, from: JSONSerialization.data(withJSONObject: payload))
        XCTAssertNil(review.lastWorkout?.avgHr)
        XCTAssertNil(review.lastWorkout?.avgPaceSKm)
        XCTAssertNil(review.lastWorkout?.elevationGainM)
    }
    func testEligibleAndConsumedTrendDecode() throws {
        let before = try Wire.decoder().decode(WorkoutReview.self, from: data("review-improving"))
        let after = try Wire.decoder().decode(WorkoutReview.self, from: data("review-keep"))
        XCTAssertTrue(before.program.eligible)
        XCTAssertEqual(before.program.evidence.count, 4)
        XCTAssertEqual(before.lastWorkout?.avgPaceSKm, 330)
        XCTAssertFalse(after.program.eligible)
        XCTAssertEqual(after.planVersion, 2)
    }
    func testDetailContextCanVetoAnImprovingTrend() throws {
        var payload = try XCTUnwrap(JSONSerialization.jsonObject(with: data("review-improving")) as? [String: Any])
        var program = try XCTUnwrap(payload["program"] as? [String: Any])
        program["eligible"] = false
        program["decision"] = "keep"
        program["context_reasons"] = ["Lap 2: FC sopra il riferimento Z2 configurato."]
        payload["program"] = program
        let review = try Wire.decoder().decode(WorkoutReview.self, from: JSONSerialization.data(withJSONObject: payload))
        XCTAssertEqual(review.program.direction, "improving")
        XCTAssertFalse(review.program.eligible)
        XCTAssertEqual(review.program.contextReasons, ["Lap 2: FC sopra il riferimento Z2 configurato."])
        let previous = try Wire.decoder().decode(WorkoutReview.self, from: data("review-improving"))
        XCTAssertNil(previous.program.contextReasons)
    }
    func testProposalPreservesExactStepsAndExplicitAcceptance() throws {
        let proposal = try Wire.decoder().decode(AdjustmentProposal.self, from: data("proposal"))
        XCTAssertEqual(proposal.baseVersion, 1)
        XCTAssertEqual(proposal.changes.count, 3)
        XCTAssertEqual(proposal.changes[0].stepChanges[0].beforeDurationS, 1800)
        XCTAssertEqual(proposal.changes[0].stepChanges[0].afterDurationS, 1890)
        XCTAssertNotNil(Wire.date(proposal.expiresAt))
        let body = try Wire.encoder().encode(Acceptance(expectedVersion: 1, confirmed: true))
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: body) as? [String: Any])
        XCTAssertEqual(object["expected_version"] as? Int, 1)
        XCTAssertEqual(object["confirmed"] as? Bool, true)
        XCTAssertNil(object["athlete_id"])
    }
    func testPlanMetadataSurvivesUploadWithoutKeyRewriting() throws {
        let response = try Wire.decoder().decode(PlanReply.self, from: data("plan"))
        let body = try Wire.encoder().encode(PlanWrite(expectedVersion: response.version, plan: response.plan))
        let uploaded = try XCTUnwrap(JSONSerialization.jsonObject(with: body) as? [String: Any])
        let original = try XCTUnwrap(JSONSerialization.jsonObject(with: data("plan")) as? [String: Any])
        XCTAssertTrue(NSDictionary(dictionary: try XCTUnwrap(uploaded["plan"] as? [String: Any])).isEqual(to: try XCTUnwrap(original["plan"] as? [String: Any])))
        XCTAssertEqual(try response.display().workouts.count, 3)
        XCTAssertEqual(try response.display().workouts[0].steps[1].target?.zone, 2)
    }
    func testHealthPayloadUsesServerNamesAndNullMetrics() throws {
        let payload = try XCTUnwrap(JSONSerialization.jsonObject(with: data("apple-health-import")) as? [String: Any])
        let array = try JSONSerialization.data(withJSONObject: try XCTUnwrap(payload["activities"]))
        let records = try Wire.decoder().decode([ImportedActivity].self, from: array)
        let encoded = try Wire.encoder().encode(ActivityImport(activities: records))
        let body = try XCTUnwrap(JSONSerialization.jsonObject(with: encoded) as? [String: Any])
        let activities = try XCTUnwrap(body["activities"] as? [[String: Any]])
        XCTAssertEqual(body["ingestion_method"] as? String, "client_import")
        XCTAssertEqual(activities[0]["avg_pace_s_km"] as? Double, 360)
        XCTAssertEqual(activities[0]["source_activity_id"] as? String, "synthetic-workout-0")
        XCTAssertNil(activities[0]["training_load"])
        XCTAssertNil(activities[0]["avgPaceSKm"])
    }
    func testUnsafeOriginsRejected() throws {
        XCTAssertEqual(try Endpoint.validate("https://coach.example.test").host, "coach.example.test")
        for origin in ["http://coach.example.test", "https://user:secret@coach.example.test", "https://coach.example.test/v1", "https://coach.example.test?token=secret", "https://coach.example.test#fragment", "file:///private"] {
            XCTAssertThrowsError(try Endpoint.validate(origin))
        }
    }
    func testMetricsAndISOParsing() {
        XCTAssertEqual(Metric.pace(nil), "—")
        XCTAssertEqual(Metric.pace(359.6), "6:00 /km")
        XCTAssertNotNil(Wire.date("2026-10-05T20:00:00Z"))
        XCTAssertNotNil(Wire.date("2026-10-05T20:00:00.123456+02:00"))
    }
    func testOnboardingProfileRoundTripsAndNoDeviceRemainsSupported() throws {
        let reply = try Wire.decoder().decode(ProfileReply.self, from: data("profile"))
        XCTAssertEqual(reply.profile.deviceVendor, "none")
        XCTAssertNil(reply.profile.weightKg)
        XCTAssertEqual(reply.profile.availability.count, 2)
        XCTAssertEqual(reply.profile.bestPerformances.first?.durationS, 1800)
        let encoded = try Wire.encoder().encode(ProfileWrite(expectedVersion: reply.version, profile: reply.profile))
        let body = try XCTUnwrap(JSONSerialization.jsonObject(with: encoded) as? [String: Any])
        XCTAssertEqual(body["expected_version"] as? Int, 1)
        let profile = try XCTUnwrap(body["profile"] as? [String: Any])
        XCTAssertEqual(profile["device_vendor"] as? String, "none")
        XCTAssertEqual(profile["coaching_consent"] as? Bool, true)
        XCTAssertNil(body["athlete_id"])
        let uploaded = try Wire.decoder().decode(TrainingProfile.self, from: JSONSerialization.data(withJSONObject: profile))
        XCTAssertEqual(uploaded.targetDate, "2027-03-01")
        XCTAssertEqual(uploaded.goalDescription, reply.profile.goalDescription)
    }
    func testManualSessionKeepsUnknownMetricsAndFeedbackDistinct() throws {
        let list = try Wire.decoder().decode(ActivityList.self, from: data("manual-activities"))
        let session = try XCTUnwrap(list.activities.first)
        XCTAssertEqual(session.source, "manual")
        XCTAssertEqual(session.evidenceKind, "self_reported")
        XCTAssertEqual(session.distanceKnown, false)
        XCTAssertNil(session.avgHr)
        XCTAssertNil(session.avgPaceSKm)
        XCTAssertEqual(session.feedback?.perceivedExertion, 7)
        XCTAssertEqual(FeedbackText.feeling(session.feedback?.feeling ?? ""), "Stanco")
        let request = ManualSessionRequest(requestId: "00000000-0000-4000-8000-000000000001", name: "Synthetic", sport: "running",
            startTime: "2026-10-05T18:00:00Z", durationMin: 30, distanceKm: nil, perceivedExertion: 7,
            feeling: "fatigued", discomfort: "none", completedAsPlanned: false, notes: "Synthetic feedback")
        let body = try XCTUnwrap(JSONSerialization.jsonObject(with: Wire.encoder().encode(request)) as? [String: Any])
        XCTAssertEqual(body["request_id"] as? String, request.requestId)
        XCTAssertEqual(body["duration_min"] as? Double, 30)
        XCTAssertEqual(body["perceived_exertion"] as? Int, 7)
        XCTAssertNil(body["distance_km"])
        XCTAssertNil(body["avg_hr"])
        XCTAssertNil(body["source"])
    }
    func testDetailedAPIPhasesUnitsAndRouteDecode() throws {
        let review = try Wire.decoder().decode(WorkoutReview.self, from: data("review-detailed"))
        let detail = try XCTUnwrap(review.detailedReview)
        let analysis = try XCTUnwrap(detail.analysis)
        XCTAssertEqual(detail.status, "ready")
        XCTAssertEqual(detail.planReference?.version, 1)
        XCTAssertEqual(detail.source, "coros")
        XCTAssertEqual(analysis.phases.count, 6)
        XCTAssertEqual(analysis.phases[1].verdict, "troppo veloce")
        XCTAssertEqual(analysis.phases[3].verdict, "in target")
        XCTAssertEqual(analysis.phases[1].target?.fast, "5:00")
        XCTAssertEqual(try XCTUnwrap(analysis.dynamics.strideM), 1.23, accuracy: 0.001)
        XCTAssertEqual(try XCTUnwrap(analysis.dynamics.gctMs), 279, accuracy: 0.001)
        XCTAssertEqual(analysis.routeSegments[0].count, 2)
        XCTAssertEqual(analysis.coverage.sampleCount, 2)
        XCTAssertEqual(analysis.coverage.reportedSampleCount, 1320)
        XCTAssertFalse(review.program.eligible)
    }
    func testStaleDetailsDecodeWithoutShowingPreviousAnalysis() throws {
        var body = try XCTUnwrap(JSONSerialization.jsonObject(with: data("review-detailed")) as? [String: Any])
        body["detailed_review"] = ["status": "stale", "version": 1, "source": "coros"]
        let review = try Wire.decoder().decode(WorkoutReview.self, from: JSONSerialization.data(withJSONObject: body))
        XCTAssertEqual(review.detailedReview?.status, "stale")
        XCTAssertNil(review.detailedReview?.analysis)
    }
    func testHealthEvidencePreservesUnitsAndDoesNotCarryMissingHeartRate() throws {
        let input: [HealthMetric:[HealthReading]] = [
            .heart:[HealthReading(start:5,end:5,value:140)], .speed:[HealthReading(start:10,end:20,value:3)],
            .stride:[HealthReading(start:10,end:20,value:1.23)], .groundContact:[HealthReading(start:10,end:20,value:0.279)],
            .steps:[HealthReading(start:0,end:60,value:170)]]
        let result=HealthEvidenceBuilder.build(readings:input,elapsed:300,active:300,lapIntervals:[],pauses:[],routes:[],cycling:false)
        XCTAssertEqual(result.samples.first?.hr,140)
        XCTAssertNil(result.samples.first(where:{$0.elapsedS==15})?.hr)
        XCTAssertEqual(try XCTUnwrap(result.dynamics.strideM),1.23,accuracy:0.001)
        XCTAssertEqual(try XCTUnwrap(result.dynamics.groundContactS),0.279,accuracy:0.001)
        XCTAssertEqual(try XCTUnwrap(result.dynamics.cadenceSpm),170,accuracy:0.001)
        let data=try Wire.encoder().encode(HealthDetailWrite(expectedDetailsVersion:0,expectedActivityHash:String(repeating:"a",count:64),details:result))
        let object=try XCTUnwrap(JSONSerialization.jsonObject(with:data) as? [String:Any])
        let details=try XCTUnwrap(object["details"] as? [String:Any])
        let samples=try XCTUnwrap(details["samples"] as? [[String:Any]])
        XCTAssertEqual(samples.first(where:{$0["speed_m_s"] != nil})?["speed_m_s"] as? Double,3)
        XCTAssertNil(samples.first?["distance_m"])
        XCTAssertNil(details["plan_version"])
        XCTAssertNil(details["plan_workout_id"])
    }
    func testHealthLapsRequireKnownActiveTimeAndCompleteDistance() {
        let laps=[HealthInterval(start:0,end:150),HealthInterval(start:150,end:300)]
        let input:[HealthMetric:[HealthReading]]=[.distance:[HealthReading(start:0,end:150,value:500),HealthReading(start:150,end:300,value:600)],.heart:[HealthReading(start:10,end:20,value:140)]]
        let full=HealthEvidenceBuilder.build(readings:input,elapsed:300,active:300,lapIntervals:laps,pauses:[],routes:[],cycling:false)
        XCTAssertEqual(full.laps.count,2);XCTAssertEqual(full.laps.first?.distanceM,500)
        let pausedUnknown=HealthEvidenceBuilder.build(readings:input,elapsed:300,active:250,lapIntervals:laps,pauses:[],routes:[],cycling:false)
        XCTAssertTrue(pausedUnknown.laps.isEmpty)
        let partial=HealthEvidenceBuilder.build(readings:[.distance:[HealthReading(start:10,end:150,value:500)]],elapsed:300,active:300,lapIntervals:laps,pauses:[],routes:[],cycling:false)
        XCTAssertNil(partial.laps.first?.distanceM)
    }
    func testHealthGPSGapsAndPointReductionStayWithinContract() {
        let locations=[HealthCoordinate(time:0,lat:45,lon:9,accuracy:5),HealthCoordinate(time:1,lat:45.001,lon:9.001,accuracy:5),
            HealthCoordinate(time:2,lat:45.002,lon:9.002,accuracy:-1),HealthCoordinate(time:3,lat:45.003,lon:9.003,accuracy:5),HealthCoordinate(time:4,lat:45.004,lon:9.004,accuracy:5)]
        let gap=HealthEvidenceBuilder.build(readings:[:],elapsed:300,active:300,lapIntervals:[],pauses:[],routes:[locations],cycling:false)
        XCTAssertEqual(gap.routeSegments.count,2)
        let heart=(0..<10000).map{HealthReading(start:Double($0),end:Double($0),value:140)}
        let route=(0..<10000).map{HealthCoordinate(time:Double($0),lat:45+Double($0)/1000000,lon:9,accuracy:5)}
        let reduced=HealthEvidenceBuilder.build(readings:[.heart:heart],elapsed:10000,active:10000,lapIntervals:[],pauses:[],routes:[route],cycling:false)
        XCTAssertLessThanOrEqual(reduced.samples.count,4000)
        XCTAssertLessThanOrEqual(reduced.routeSegments.reduce(0){$0+$1.count},2000)
        XCTAssertEqual(reduced.reportedSampleCount,10000)
    }
    func testActivityQueryUsesQueryParametersRatherThanEscapedPath() async throws {
        let api = APIClient(endpoint: try Endpoint.validate("https://coach.example.test"), token: "synthetic-test-only-token", protocolClasses: [FixtureProtocol.self])
        let list: ActivityList = try await api.request("v1/activities", query: [URLQueryItem(name: "limit", value: "50")])
        XCTAssertEqual(list.activities.first?.feedback?.perceivedExertion, 7)
    }
    func testAuthenticatedTransportAndServerConflict() async throws {
        let api = APIClient(endpoint: try Endpoint.validate("https://coach.example.test"), token: "synthetic-test-only-token", protocolClasses: [FixtureProtocol.self])
        let review: WorkoutReview = try await api.request("v1/review/workout")
        XCTAssertTrue(review.program.eligible)
        do {
            let _: ApplyReply = try await api.request("v1/review/adjustments/stale/apply", method: "POST", body: Wire.encoder().encode(Acceptance(expectedVersion: 1, confirmed: true)))
            XCTFail("Stale evidence must not succeed")
        } catch let error as ServiceError { XCTAssertEqual(error.status, 409); XCTAssertEqual(error.code, "proposal_stale") }
        let _: EmptyReply = try await api.request("v1/auth/logout", method: "POST")
    }
}

private final class FixtureProtocol: URLProtocol {
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        guard request.value(forHTTPHeaderField: "Authorization") == "Bearer synthetic-test-only-token" else {
            client?.urlProtocol(self, didFailWithError: URLError(.userAuthenticationRequired)); return
        }
        let status: Int
        let data: Data
        if request.url?.path == "/v1/review/workout" {
            guard let url = Bundle(for: ContractTests.self).url(forResource: "review-improving", withExtension: "json", subdirectory: "Fixtures"), let fixture = try? Data(contentsOf: url) else {
                client?.urlProtocol(self, didFailWithError: URLError(.fileDoesNotExist)); return
            }
            status = 200; data = fixture
        } else if request.url?.path == "/v1/activities", request.url?.query == "limit=50" {
            guard let url = Bundle(for: ContractTests.self).url(forResource: "manual-activities", withExtension: "json", subdirectory: "Fixtures"), let fixture = try? Data(contentsOf: url) else {
                client?.urlProtocol(self, didFailWithError: URLError(.fileDoesNotExist)); return
            }
            status = 200; data = fixture
        } else if request.url?.path == "/v1/auth/logout" { status = 204; data = Data() }
        else { status = 409; data = Data(#"{"detail":"Generate a new preview","code":"proposal_stale"}"#.utf8) }
        guard let url = request.url, let response = HTTPURLResponse(url: url, statusCode: status, httpVersion: nil, headerFields: ["Content-Type": "application/json"]) else { return }
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: data)
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}

final class ChatGPTContractTests: XCTestCase {
    private func account(_ clientID: String, subject: String = "same-person", token: String = "synthetic", welcomed: Bool = false) -> ChatGPTCredential {
        ChatGPTCredential(clientID: clientID, identity: .init(subject: subject, email: "same@example.test"),
                          accessToken: token, refreshToken: "synthetic-refresh-" + token, idToken: "synthetic-id-" + token,
                          scopes: ["openid", "resource.invoke", "chatgpt.tokens.use.direct"], expiresAt: Date(), welcomed: welcomed, nonce: "synthetic")
    }
    private func vaultQuery(_ account: String) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: "EnduranceCoach.ChatGPT", kSecAttrAccount as String: account]
    }
    private func insertLegacy<T: Encodable>(_ value: T, account: String) throws {
        var query = vaultQuery(account)
        query[kSecValueData as String] = try JSONEncoder().encode(value)
        query[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        XCTAssertEqual(SecItemAdd(query as CFDictionary, nil), errSecSuccess)
    }
    func testKeychainRoundTripAndOwnerIsolation() throws {
        let origin = "https://registry-test.example.invalid"
        let first = ChatGPTVault.binding(endpoint: origin, athleteID: UUID().uuidString)
        let second = ChatGPTVault.binding(endpoint: origin, athleteID: UUID().uuidString)
        defer { try? ChatGPTVault.clear(first); try? ChatGPTVault.clear(second) }
        var book = ChatGPTAccountBook()
        try book.accept(account("oaiapp_first", token: "first"))
        try book.accept(account("oaiapp_second", token: "second"))
        try ChatGPTVault.saveBook(book, binding: first)
        XCTAssertEqual(try ChatGPTVault.book(first).activeCredential?.accessToken, "second")
        XCTAssertTrue(try ChatGPTVault.book(second).registrations.isEmpty)
        book.signOut("oaiapp_second")
        try ChatGPTVault.saveBook(book, binding: first)
        let restored = try ChatGPTVault.book(first)
        XCTAssertNil(restored.activeClientID)
        XCTAssertEqual(restored.registrations[0].credential?.accessToken, "first")
        XCTAssertNil(restored.registrations[1].credential)
    }
    func testKeychainMigratesLegacyCredentialAndPendingClient() throws {
        let binding = ChatGPTVault.binding(endpoint: "https://registry-test.example.invalid", athleteID: UUID().uuidString)
        defer { try? ChatGPTVault.clear(binding) }
        try insertLegacy(account("oaiapp_legacy", token: "legacy"), account: "account-" + binding)
        try insertLegacy("oaiapp_pending", account: "retry-" + binding)
        let migrated = try ChatGPTVault.book(binding)
        XCTAssertEqual(migrated.activeCredential?.accessToken, "legacy")
        XCTAssertEqual(migrated.registrations.count, 2)
        XCTAssertNil(migrated.registrations[1].credential)
        XCTAssertEqual(SecItemCopyMatching(vaultQuery("account-" + binding) as CFDictionary, nil), errSecItemNotFound)
        XCTAssertEqual(SecItemCopyMatching(vaultQuery("retry-" + binding) as CFDictionary, nil), errSecItemNotFound)
        XCTAssertEqual(try ChatGPTVault.book(binding).registrations.count, 2)
    }
    func testKeychainClearRemovesAllFormatsAndPreservesHost() throws {
        let binding = ChatGPTVault.binding(endpoint: "https://registry-test.example.invalid", athleteID: UUID().uuidString)
        defer { try? ChatGPTVault.clear(binding) }
        let host = try ChatGPTVault.hostID()
        var book = ChatGPTAccountBook(); try book.accept(account("oaiapp_first"))
        try ChatGPTVault.saveBook(book, binding: binding)
        try insertLegacy(account("oaiapp_legacy"), account: "account-" + binding)
        try insertLegacy("oaiapp_pending", account: "retry-" + binding)
        try ChatGPTVault.clear(binding)
        for prefix in ["registry-", "account-", "retry-"] {
            XCTAssertEqual(SecItemCopyMatching(vaultQuery(prefix + binding) as CFDictionary, nil), errSecItemNotFound)
        }
        XCTAssertEqual(try ChatGPTVault.hostID(), host)
        XCTAssertTrue(try ChatGPTVault.book(binding).registrations.isEmpty)
    }
    func testSeparateRegistrationsMayShareEmailAndSubject() throws {
        var book = ChatGPTAccountBook()
        try book.accept(account("oaiapp_first", token: "first", welcomed: true))
        try book.accept(account("oaiapp_second", token: "second"))
        XCTAssertEqual(book.registrations.count, 2)
        XCTAssertNotEqual(book.registrations[0].label, book.registrations[1].label)
        XCTAssertEqual(book.registrations[0].credential?.accessToken, "first")
        XCTAssertEqual(book.activeCredential?.accessToken, "second")
        XCTAssertTrue(book.registrations[0].welcomed)
        XCTAssertFalse(book.registrations[1].welcomed)
        try book.validate()
    }
    func testPendingAndFailedReauthorizationCannotReplaceActiveIdentity() throws {
        var book = ChatGPTAccountBook()
        try book.accept(account("oaiapp_first", token: "first"))
        try book.retainIssued("oaiapp_pending")
        XCTAssertNil(book.registrations[1].credential)
        XCTAssertEqual(book.activeClientID, "oaiapp_first")
        XCTAssertThrowsError(try book.accept(account("oaiapp_first", subject: "another-person", token: "wrong")))
        XCTAssertEqual(book.activeCredential?.identity.subject, "same-person")
        XCTAssertEqual(book.activeCredential?.accessToken, "first")
    }
    func testSigningOutOneAccountKeepsOtherCredentialsAndStableMapping() throws {
        var book = ChatGPTAccountBook()
        try book.accept(account("oaiapp_first", token: "first", welcomed: true))
        let label = book.registrations[0].label
        try book.accept(account("oaiapp_second", token: "second"))
        book.signOut("oaiapp_second")
        XCTAssertNil(book.activeClientID)
        XCTAssertEqual(book.registrations[0].credential?.accessToken, "first")
        XCTAssertNotNil(book.registrations[1].identity)
        XCTAssertNil(book.registrations[1].credential)
        try book.accept(account("oaiapp_first", token: "renewed", welcomed: true))
        XCTAssertEqual(book.registrations[0].label, label)
        XCTAssertEqual(book.registrations.count, 2)
        book.signOutAll()
        XCTAssertNil(book.activeCredential)
        XCTAssertTrue(book.registrations.allSatisfy { $0.credential == nil })
        XCTAssertEqual(book.registrations[0].identity?.subject, "same-person")
        XCTAssertTrue(book.registrations[0].welcomed)
    }
    func testMigrationAndRoundTripPreserveIssuedClientAndPendingRetry() throws {
        let original = account("oaiapp_first", token: "legacy", welcomed: true)
        let book = try ChatGPTAccountBook.migrated(credential: original, retryClient: "oaiapp_retry")
        let restored = try JSONDecoder().decode(ChatGPTAccountBook.self, from: JSONEncoder().encode(book))
        try restored.validate()
        XCTAssertEqual(restored.activeClientID, original.clientID)
        XCTAssertEqual(restored.activeCredential?.refreshToken, original.refreshToken)
        XCTAssertEqual(restored.registrations[1].clientID, "oaiapp_retry")
        XCTAssertNil(restored.registrations[1].identity)
        XCTAssertThrowsError(try ChatGPTAccountBook.migrated(credential: nil, retryClient: "dynamic_agent_client"))
    }
    func testRegistryRejectsTokenClientMixingDuplicateAndUnknownVersion() throws {
        var book = ChatGPTAccountBook()
        try book.accept(account("oaiapp_first"))
        let data = try JSONEncoder().encode(book)
        var value = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        let rows = try XCTUnwrap(value["registrations"] as? [[String: Any]])
        var mixed = try XCTUnwrap(rows[0]["credential"] as? [String: Any])
        mixed["clientID"] = "oaiapp_other"
        var row = rows[0]; row["credential"] = mixed
        value["registrations"] = [row]
        let invalid = try JSONDecoder().decode(ChatGPTAccountBook.self, from: JSONSerialization.data(withJSONObject: value))
        XCTAssertThrowsError(try invalid.validate())
        value["registrations"] = rows + rows
        let duplicate = try JSONDecoder().decode(ChatGPTAccountBook.self, from: JSONSerialization.data(withJSONObject: value))
        XCTAssertThrowsError(try duplicate.validate())
        value["registrations"] = rows; value["schemaVersion"] = 2
        let newer = try JSONDecoder().decode(ChatGPTAccountBook.self, from: JSONSerialization.data(withJSONObject: value))
        XCTAssertThrowsError(try newer.validate())
    }
    func testPKCEAndFirstReturningAuthorization() throws {
        XCTAssertEqual(ChatGPTAuthorization.challenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"), "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM")
        let first = try ChatGPTAuthorization.Attempt(port: 54321)
        let host = "urn:uuid:" + UUID().uuidString
        let parts = try XCTUnwrap(URLComponents(url: first.authorizationURL(hostID: host), resolvingAgainstBaseURL: false))
        let query = Dictionary(uniqueKeysWithValues: (parts.queryItems ?? []).map { ($0.name, $0.value ?? "") })
        XCTAssertEqual(query["agent_name_hint"], "EnduranceCoach")
        XCTAssertNil(query["agent_name"])
        XCTAssertEqual(query["redirect_uri"], "http://127.0.0.1:54321/auth/callback")
        XCTAssertEqual(query["ext_agent_host_id"], host)
        let returning = try ChatGPTAuthorization.Attempt(port: 12345, clientID: "oaiapp_synthetic")
        let again = try XCTUnwrap(URLComponents(url: returning.authorizationURL(hostID: host), resolvingAgainstBaseURL: false))
        XCTAssertFalse((again.queryItems ?? []).contains { $0.name == "agent_name_hint" })
        XCTAssertNotEqual(first.state, returning.state)
        XCTAssertNotEqual(first.nonce, returning.nonce)
    }
    func testCallbackRejectsStatePortDuplicatesExpiredAndChangedClient() throws {
        let now = Date(timeIntervalSince1970: 1_790_000_000)
        let attempt = try ChatGPTAuthorization.Attempt(port: 54321, now: now)
        let good = "http://127.0.0.1:54321/auth/callback?state=\(attempt.state)&code=synthetic&client_id=oaiapp_synthetic"
        XCTAssertEqual(try attempt.callback(XCTUnwrap(URL(string: good)), now: now).clientID, "oaiapp_synthetic")
        for bad in [good.replacingOccurrences(of: attempt.state, with: "wrong"), good + "&code=duplicate",
                    good.replacingOccurrences(of: "54321", with: "12345"), good.replacingOccurrences(of: "127.0.0.1", with: "localhost"),
                    good.replacingOccurrences(of: "http:", with: "https:"), good + "#fragment",
                    good.replacingOccurrences(of: "oaiapp_synthetic", with: "dynamic_agent_client")] {
            XCTAssertThrowsError(try attempt.callback(XCTUnwrap(URL(string: bad)), now: now))
        }
        XCTAssertThrowsError(try attempt.callback(XCTUnwrap(URL(string: good)), now: now.addingTimeInterval(601)))
        let returning = try ChatGPTAuthorization.Attempt(port: 54321, clientID: "oaiapp_one", now: now)
        XCTAssertThrowsError(try returning.callback(XCTUnwrap(URL(string: "http://127.0.0.1:54321/auth/callback?state=\(returning.state)&code=test&client_id=oaiapp_other")), now: now))
        XCTAssertThrowsError(try attempt.callback(XCTUnwrap(URL(string: "http://127.0.0.1:54321/auth/callback?state=\(attempt.state)&error=access_denied")), now: now)) { error in
            XCTAssertEqual((error as? ServiceError)?.code, "chatgpt_cancelled")
        }
    }
    func testSignedIdentityAndClaimRejections() throws {
        // A transient RSA key exists only in test-process memory; no private key or live token is bundled.
        let attributes: [String: Any] = [kSecAttrKeyType as String: kSecAttrKeyTypeRSA, kSecAttrKeySizeInBits as String: 2048]
        let key = try XCTUnwrap(SecKeyCreateRandomKey(attributes as CFDictionary, nil))
        let publicKey = try XCTUnwrap(SecKeyCopyPublicKey(key))
        let exported = try XCTUnwrap(SecKeyCopyExternalRepresentation(publicKey, nil)) as Data
        let bytes = Array(exported); var offset = 1
        func length() -> Int {
            let value = Int(bytes[offset]); offset += 1
            if value < 128 { return value }
            var count = 0
            for _ in 0..<(value & 127) { count = (count << 8) | Int(bytes[offset]); offset += 1 }
            return count
        }
        _ = length()
        func integer() -> Data {
            offset += 1; let count = length()
            var value = Array(bytes[offset..<(offset + count)]); offset += count
            while value.count > 1 && value[0] == 0 { value.removeFirst() }
            return Data(value)
        }
        let modulus = integer(), exponent = integer()
        let jwks = try JSONSerialization.data(withJSONObject: ["keys": [["kid": "synthetic", "kty": "RSA", "alg": "RS256",
            "n": ChatGPTAuthorization.base64URL(modulus), "e": ChatGPTAuthorization.base64URL(exponent)]]])
        let now = Date(timeIntervalSince1970: 1_790_000_000)
        let claims: [String: Any] = ["iss": ChatGPTAuthorization.issuer, "aud": "oaiapp_test", "sub": "synthetic-athlete",
                                  "nonce": "test-nonce", "iat": now.timeIntervalSince1970, "exp": now.timeIntervalSince1970 + 300]
        func signed(_ claims: [String: Any], algorithm: String = "RS256") throws -> String {
            let header = ChatGPTAuthorization.base64URL(try JSONSerialization.data(withJSONObject: ["kid": "synthetic", "alg": algorithm]))
            let payload = ChatGPTAuthorization.base64URL(try JSONSerialization.data(withJSONObject: claims))
            let message = header + "." + payload
            let signature = try XCTUnwrap(SecKeyCreateSignature(key, .rsaSignatureMessagePKCS1v15SHA256, Data(message.utf8) as CFData, nil)) as Data
            return message + "." + ChatGPTAuthorization.base64URL(signature)
        }
        let token = try signed(claims)
        XCTAssertEqual(try ChatGPTAuthorization.validateIDToken(token, jwks: jwks, clientID: "oaiapp_test", nonce: "test-nonce", now: now).subject, "synthetic-athlete")
        let changes: [[String: Any]] = [["iss": "https://example.invalid"], ["aud": "oaiapp_other"], ["nonce": "wrong"],
                                     ["exp": now.timeIntervalSince1970 - 1], ["iat": now.timeIntervalSince1970 + 600]]
        for change in changes {
            let invalid = claims.merging(change) { _, new in new }
            XCTAssertThrowsError(try ChatGPTAuthorization.validateIDToken(signed(invalid), jwks: jwks, clientID: "oaiapp_test", nonce: "test-nonce", now: now))
        }
        XCTAssertThrowsError(try ChatGPTAuthorization.validateIDToken(signed(claims, algorithm: "none"), jwks: jwks, clientID: "oaiapp_test", nonce: "test-nonce", now: now))
        var parts = token.split(separator: ".").map(String.init)
        parts[1] = ChatGPTAuthorization.base64URL(try JSONSerialization.data(withJSONObject: claims.merging(["sub": "tampered"]) { _, new in new }))
        XCTAssertThrowsError(try ChatGPTAuthorization.validateIDToken(parts.joined(separator: "."), jwks: jwks, clientID: "oaiapp_test", nonce: "test-nonce", now: now))
    }
    func testAccountCatalogPreservesOrderAndHidesUnavailableModels() throws {
        let body = Data(#"{"models":[{"slug":"second","display_name":"Second","visibility":"list"},{"slug":"hidden","display_name":"Hidden","visibility":"hide"},{"slug":"first","display_name":"First","visibility":"list"},{"slug":"second","display_name":"Duplicate","visibility":"list"}]}"#.utf8)
        XCTAssertEqual(try ChatGPTHTTP.catalog(body).map(\.id), ["second", "first"])
        XCTAssertThrowsError(try ChatGPTHTTP.catalog(Data(#"{"data":[{"id":"unrelated-catalog"}]}"#.utf8)))
    }
    func testOnlyCompletedAssistantTextIsAccepted() throws {
        XCTAssertNil(try ChatGPTHTTP.completedText(#"{"type":"response.output_text.delta","delta":"partial"}"#))
        XCTAssertNil(try ChatGPTHTTP.completedText("[DONE]"))
        let finished = #"{"type":"response.completed","response":{"status":"completed","output":[{"type":"message","role":"assistant","content":[{"type":"output_text","text":"Seduta riuscita: regola il ritmo."}]},{"type":"message","role":"user","content":[{"type":"output_text","text":"ignored"}]}]}}"#
        XCTAssertEqual(try ChatGPTHTTP.completedText(finished), "Seduta riuscita: regola il ritmo.")
        for type in ["response.failed", "response.incomplete", "error"] {
            XCTAssertThrowsError(try ChatGPTHTTP.completedText("{\"type\":\"\(type)\"}"))
        }
        XCTAssertThrowsError(try ChatGPTHTTP.completedText(finished.replacingOccurrences(of: "\"status\":\"completed\"", with: "\"status\":\"incomplete\"")))
    }
    func testLoopbackRequestShapeAndAccountBinding() throws {
        XCTAssertEqual(ChatGPTLoopback.requestURL("GET /auth/callback?state=test HTTP/1.1", port: 54321)?.host, "127.0.0.1")
        for request in ["POST /auth/callback?code=x HTTP/1.1", "GET https://example.invalid/ HTTP/1.1", "GET /other?x=y HTTP/1.1", "GET /auth/callback?x=y HTTP/2"] {
            XCTAssertNil(ChatGPTLoopback.requestURL(request, port: 54321))
        }
        XCTAssertNotEqual(ChatGPTVault.binding(endpoint: "https://a.invalid", athleteID: "one"), ChatGPTVault.binding(endpoint: "https://a.invalid", athleteID: "two"))
        XCTAssertNotEqual(ChatGPTVault.binding(endpoint: "https://a.invalid", athleteID: "one"), ChatGPTVault.binding(endpoint: "https://b.invalid", athleteID: "one"))
    }
    func testIdentityOnlyCannotEnableInferenceAndRefreshCanOmitScope() throws {
        let reply = try Wire.decoder().decode(ChatGPTTokenReply.self, from: Data(#"{"access_token":"synthetic","token_type":"Bearer","expires_in":300}"#.utf8))
        XCTAssertNil(reply.scope)
        var credential = ChatGPTCredential(clientID: "oaiapp_test", identity: .init(subject: "test", email: nil),
                                          accessToken: "synthetic", refreshToken: nil, idToken: "synthetic",
                                          scopes: ["openid", "profile", "email", "resource.invoke"],
                                          expiresAt: Date(), welcomed: false, nonce: "synthetic")
        XCTAssertFalse(credential.permitsInference)
        credential.scopes.append("chatgpt.tokens.use.direct")
        XCTAssertTrue(credential.permitsInference)
    }
    func testRealLoopbackListenerReturnsStaticPageWithoutEchoingCode() async throws {
        let listener = ChatGPTLoopback()
        let port = try await listener.start { url in url.query == "code=synthetic-private-value" }
        defer { listener.stop() }
        let session = URLSession(configuration: .ephemeral)
        defer { session.invalidateAndCancel() }
        let url = try XCTUnwrap(URL(string: "http://127.0.0.1:\(port)/auth/callback?code=synthetic-private-value"))
        let (data, response) = try await session.data(from: url)
        XCTAssertEqual((response as? HTTPURLResponse)?.statusCode, 200)
        XCTAssertFalse(String(decoding: data, as: UTF8.self).contains("synthetic-private-value"))
        XCTAssertEqual((response as? HTTPURLResponse)?.value(forHTTPHeaderField: "Cache-Control"), "no-store")
    }
}
