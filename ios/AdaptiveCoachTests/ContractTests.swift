import XCTest
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
