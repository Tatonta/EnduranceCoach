import Foundation

// Preserve arbitrary athlete metadata and the complete validated plan when importing JSON.
enum JSONValue: Codable, Equatable {
    case object([String: JSONValue]), array([JSONValue]), string(String), number(Double), bool(Bool), null
    init(from decoder: Decoder) throws {
        let value = try decoder.singleValueContainer()
        if value.decodeNil() { self = .null }
        else if let item = try? value.decode(Bool.self) { self = .bool(item) }
        else if let item = try? value.decode(Double.self) { self = .number(item) }
        else if let item = try? value.decode(String.self) { self = .string(item) }
        else if let item = try? value.decode([String: JSONValue].self) { self = .object(item) }
        else { self = .array(try value.decode([JSONValue].self)) }
    }
    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .object(let value): try container.encode(value)
        case .array(let value): try container.encode(value)
        case .string(let value): try container.encode(value)
        case .number(let value): try container.encode(value)
        case .bool(let value): try container.encode(value)
        case .null: try container.encodeNil()
        }
    }
}

enum Wire {
    static func decoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return decoder
    }
    static func encoder() -> JSONEncoder {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        return encoder
    }
    static func iso(_ date: Date) -> String { ISO8601DateFormatter().string(from: date) }
    static func date(_ value: String) -> Date? {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter.date(from: value) ?? ISO8601DateFormatter().date(from: value)
    }
}

struct EmptyReply: Decodable {}
struct Identity: Codable { let id: String; let email: String; let timezone: String }
struct LoginReply: Decodable { let accessToken: String; let expiresAt: String }
struct Credentials: Encodable { let email: String; let password: String }
struct Registration: Encodable { let email: String; let password: String; let timezone: String }
struct SessionSecret: Codable { let endpoint: String; let token: String; let athleteID: String }

struct ActivityMetrics: Decodable {
    let activityId: String
    let name: String
    let sport: String
    let date: String
    let startTime: String
    let distanceM: Double
    let durationS: Double
    let avgPaceSKm: Double?
    let avgHr: Double?
    let elevationGainM: Double?
    let source: String
    let evidenceKind: String?
    let distanceKnown: Bool?
    let feedback: SessionFeedback?
}
struct SessionFeedback: Decodable {
    let perceivedExertion: Int?
    let feeling: String
    let discomfort: String
    let completedAsPlanned: Bool?
    let notes: String
}
struct ActivityList: Decodable { let activities: [ActivityMetrics] }
struct ManualSessionRequest: Encodable {
    let requestId: String
    let name: String
    let sport: String
    let startTime: String
    let durationMin: Double
    let distanceKm: Double?
    let perceivedExertion: Int?
    let feeling: String
    let discomfort: String
    let completedAsPlanned: Bool?
    let notes: String
}
struct WorkoutMatch: Decodable {
    let plannedName: String?
    let status: String
    let note: String?
}
struct TrendEvidence: Decodable {
    let activityId: String
    let name: String
    let date: String
    let avgPaceSKm: Double
    let avgHr: Double
}
struct ProgramAdvice: Decodable {
    let decision: String
    let eligible: Bool
    let direction: String?
    let reason: String
    let policy: String
    let evidence: [TrendEvidence]
    let contextReasons: [String]?
}
struct WorkoutReview: Decodable {
    let generatedAt: String
    let lastWorkout: ActivityMetrics?
    let match: WorkoutMatch?
    let verdict: String
    let advice: [String]
    let program: ProgramAdvice
    let limitations: [String]
    let planVersion: Int
    let detailedReview: DetailedReview?
}

struct DetailedReview: Decodable {
    let status: String
    let version: Int
    let source: String
    let analysis: DetailedAnalysis?
    let planReference: DetailedPlanReference?
    let limitations: [String]?
}
struct DetailedPlanReference: Decodable { let version: Int?; let workoutId: String?; let verification: String }
struct DetailedAnalysis: Decodable {
    let phases: [DetailedPhase]
    let laps: [DetailedLap]
    let series: [DetailedSample]
    let routeSegments: [[[Double]]]
    let dynamics: DetailedDynamics
    let positive: [String]
    let issues: [String]
    let actions: [String]
    let verdict: String
    let coverage: DetailedCoverage
    let coverageNote: String
}
struct DetailedCoverage: Decodable { let lapCount: Int; let sampleCount: Int; let gpsPoints: Int; let reportedSampleCount: Int? }
struct DetailedDynamics: Decodable {
    let cadenceSpm: Double?
    let cadenceRpm: Double?
    let strideM: Double?
    let gctMs: Double?
    let verticalCm: Double?
    let verticalRatioPercent: Double?
    let powerW: Double?
}
struct DetailedPhase: Decodable, Identifiable {
    var id: Int { number }
    let number: Int
    let name: String
    let type: String
    let durationS: Double
    let distanceM: Double?
    let paceSKm: Double?
    let avgHr: Double?
    let verdict: String
    let target: PlannedTarget?
    let plannedDurationS: Double?
    let durationCompliance: String?
    let lapNumbers: [Int]
    let hrMeanDifferenceBpm: Double?
}
struct DetailedLap: Decodable, Identifiable {
    var id: Int { lap }
    let lap: Int
    let phase: String
    let durationS: Double
    let distanceM: Double?
    let paceSKm: Double?
    let avgHr: Double?
    let maxHr: Double?
    let strideM: Double?
    let cadenceSpm: Double?
    let powerW: Double?
    let qualityFlags: [String]
}
struct DetailedSample: Decodable, Identifiable {
    var id: Double { elapsedS }
    let elapsedS: Double
    let distanceM: Double?
    let paceSKm: Double?
    let hr: Double?
    let segment: Int
}
struct StepChange: Decodable {
    let type: String
    let iterations: Int
    let beforeDurationS: Double
    let afterDurationS: Double
}
struct WorkoutChange: Decodable, Identifiable {
    var id: String { workoutId }
    let workoutId: String
    let date: String
    let name: String
    let beforeDurationMin: Double
    let afterDurationMin: Double
    let description: String
    let stepChanges: [StepChange]
}
struct AdjustmentProposal: Decodable, Identifiable {
    var id: String { proposalId }
    let proposalId: String
    let baseVersion: Int
    let expiresAt: String
    let reason: String
    let changes: [WorkoutChange]
}
struct Acceptance: Encodable { let expectedVersion: Int; let confirmed: Bool }
struct ApplyReply: Decodable { let status: String; let version: Int; let vendorSync: String }

struct PlanReply: Decodable {
    let version: Int
    let plan: JSONValue
    func display() throws -> TrainingPlan {
        // JSONValue object keys must remain untouched, including user-supplied metadata.
        try Wire.decoder().decode(TrainingPlan.self, from: JSONEncoder().encode(plan))
    }
}
struct PlanWrite: Encodable { let expectedVersion: Int; let plan: JSONValue }
struct TrainingPlan: Decodable {
    let planName: String
    let goal: String
    let notes: [String]
    let workouts: [PlannedWorkout]
}
struct PlannedWorkout: Decodable, Identifiable {
    let id: String?
    let date: String
    let name: String
    let sport: String
    let estimatedDurationMin: Double?
    let description: String
    let steps: [PlannedStep]
    var stableID: String { id ?? "\(date)-\(sport)" }
}
struct PlannedStep: Decodable {
    let type: String
    let durationS: Double?
    let durationMin: Double?
    let distanceM: Double?
    let iterations: Int?
    let steps: [PlannedStep]
    let target: PlannedTarget?
}
struct PlannedTarget: Decodable {
    let type: String
    let zone: Int?
    let slow: String?
    let fast: String?
    var description: String {
        if type == "hr_zone" { return "FC zona \(zone ?? 0)" }
        return "\(fast ?? "—")–\(slow ?? "—") /km"
    }
}
struct Vendor: Decodable, Identifiable {
    let id: String
    let name: String
    let status: String
    let notes: String
}
struct IntegrationsReply: Decodable { let vendors: [Vendor]; let liveVendorConnections: Int }

struct ImportedActivity: Codable, Identifiable {
    var id: String { source + ":" + sourceActivityId }
    let source: String
    let sourceActivityId: String
    var name: String
    let sport: String
    let activityType: String
    let startTime: String
    let distanceM: Double
    let durationS: Double
    let elapsedDurationS: Double
    let avgPaceSKm: Double?
    let avgHr: Double?
    let maxHr: Double?
    let elevationGainM: Double?
    let trainingLoad: Double?
    let aerobicTrainingEffect: Double?
    let workoutId: String
}
struct ActivityImport: Encodable {
    let ingestionMethod = "client_import"
    let activities: [ImportedActivity]
}
struct ImportReply: Decodable {
    let imported: Int
    let uniqueWorkouts: Int
    let sourceActivityHashes: [ImportedSourceHash]?
}
struct ImportedSourceHash: Decodable { let source: String; let sourceActivityId: String; let activityHash: String }
struct DetailStateReply: Decodable { let status: String; let version: Int; let activityHash: String }
struct AccountDeletion: Encodable { let password: String; let confirmed: Bool }

struct TrainingDay: Codable, Identifiable {
    var id: Int { weekday }
    var weekday: Int
    var minutes: Int
}
struct BestPerformance: Codable, Identifiable {
    var id: String { "\(sport)-\(distanceM)-\(durationS)-\(date ?? "")" }
    var sport = "running"
    var distanceM = 5000.0
    var durationS = 1800.0
    var date: String? = nil
    var note = ""
}
struct TrainingProfile: Codable {
    var schemaVersion = 1
    var primarySport = "running"
    var goalType = "fitness"
    var goalDescription = ""
    var targetDate: String? = nil
    var deadlineFlexible = true
    var ageYears: Int? = nil
    var weightKg: Double? = nil
    var heightCm: Double? = nil
    var deviceVendor = "none"
    var deviceModel = ""
    var heartRateSensor = false
    var powerMeter = false
    var runningYears = 0.0
    var cyclingYears = 0.0
    var recentRunningKmWeek = 0.0
    var recentCyclingKmWeek = 0.0
    var experienceNotes = ""
    var gymSessionsWeek = 0
    var gymNotes = ""
    var availability: [TrainingDay] = []
    var bestPerformances: [BestPerformance] = []
    var constraints = ""
    var coachingConsent = false
}
struct ProfileReply: Decodable { let version: Int; let profile: TrainingProfile; let updatedAt: String }
struct ProfileWrite: Encodable { let expectedVersion: Int; let profile: TrainingProfile }
struct CoachingContextReply: Decodable {
    let context: JSONValue
    let contextHash: String
    let inferencePerformed: Bool
}

enum Metric {
    static func pace(_ value: Double?) -> String {
        guard let value, value.isFinite, value > 0 else { return "—" }
        let seconds = Int(value.rounded())
        return String(format: "%d:%02d /km", seconds / 60, seconds % 60)
    }
    static func duration(_ seconds: Double) -> String { "\(Int((seconds / 60).rounded())) min" }
}
