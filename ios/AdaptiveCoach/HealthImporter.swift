import Foundation
import HealthKit

@MainActor
final class HealthImporter {
    // Do not open a HealthKit connection at launch; wait for the explicit import action.
    private lazy var store = HKHealthStore()
    private let heart = HKQuantityType(.heartRate)
    private let runningDistance = HKQuantityType(.distanceWalkingRunning)
    private let cyclingDistance = HKQuantityType(.distanceCycling)

    func preview() async throws -> [ImportedActivity] {
        guard HKHealthStore.isHealthDataAvailable() else {
            throw ServiceError(status: 0, code: "health_unavailable", message: "Apple Health non è disponibile su questo dispositivo.")
        }
        // Read-only. Authorization completion does not establish whether read access was granted.
        try await store.requestAuthorization(toShare: [], read: [HKObjectType.workoutType(), heart, runningDistance, cyclingDistance])
        let now = Date()
        let earliest = now.addingTimeInterval(-42 * 86_400)
        let predicate = HKQuery.predicateForSamples(withStart: earliest, end: now, options: .strictStartDate)
        let workouts: [HKWorkout] = try await withCheckedThrowingContinuation { continuation in
            let query = HKSampleQuery(sampleType: HKObjectType.workoutType(), predicate: predicate, limit: 501,
                                      sortDescriptors: [NSSortDescriptor(key: HKSampleSortIdentifierStartDate, ascending: false)]) { _, samples, error in
                if let error { continuation.resume(throwing: error) }
                else { continuation.resume(returning: (samples ?? []).compactMap { $0 as? HKWorkout }) }
            }
            store.execute(query)
        }
        guard workouts.count <= 500 else {
            throw ServiceError(status: 0, code: "health_limit", message: "Oltre 500 workout in 42 giorni: importazione interrotta per evitare una cronologia incompleta.")
        }
        var records: [ImportedActivity] = []
        for workout in workouts where workout.endDate <= now && workout.duration > 0 {
            let sport: String
            let name: String
            let quantity: HKQuantityType?
            switch workout.workoutActivityType {
            case .running: sport = "running"; name = "Corsa"; quantity = runningDistance
            case .cycling: sport = "cycling"; name = "Bici"; quantity = cyclingDistance
            case .traditionalStrengthTraining, .functionalStrengthTraining:
                sport = "strength"; name = "Forza"; quantity = nil
            default: sport = "other"; name = "Allenamento"; quantity = nil
            }
            let distance = quantity.flatMap { workout.statistics(for: $0)?.sumQuantity()?.doubleValue(for: .meter()) } ?? 0
            let statistics = try await heartStatistics(workout)
            let unit = HKUnit.count().unitDivided(by: .minute())
            let average = statistics?.averageQuantity()?.doubleValue(for: unit)
            let maximum = statistics?.maximumQuantity()?.doubleValue(for: unit)
            let ascent = (workout.metadata?[HKMetadataKeyElevationAscended] as? HKQuantity)?.doubleValue(for: .meter())
            records.append(ImportedActivity(
                source: "apple_health", sourceActivityId: workout.uuid.uuidString.lowercased(), name: name,
                sport: sport, activityType: sport, startTime: Wire.iso(workout.startDate), distanceM: max(0, distance),
                durationS: workout.duration, elapsedDurationS: max(workout.duration, workout.endDate.timeIntervalSince(workout.startDate)),
                avgPaceSKm: sport == "running" && distance > 0 ? workout.duration / (distance / 1000) : nil,
                avgHr: validHeartRate(average), maxHr: validHeartRate(maximum),
                elevationGainM: ascent.flatMap { $0.isFinite && $0 >= 0 ? $0 : nil },
                trainingLoad: nil, aerobicTrainingEffect: nil, workoutId: ""))
        }
        return records
    }
    private func validHeartRate(_ value: Double?) -> Double? {
        value.flatMap { $0.isFinite && $0 > 0 && $0 <= 250 ? $0 : nil }
    }
    private func heartStatistics(_ workout: HKWorkout) async throws -> HKStatistics? {
        try await withCheckedThrowingContinuation { continuation in
            // Only samples associated with this workout. Do not substitute unrelated all-day HR.
            let query = HKStatisticsQuery(quantityType: heart, quantitySamplePredicate: HKQuery.predicateForObjects(from: workout),
                                          options: [.discreteAverage, .discreteMax]) { _, result, error in
                if let error = error as? HKError, error.code == .errorNoData {
                    continuation.resume(returning: nil)
                } else if let error { continuation.resume(throwing: error) }
                else { continuation.resume(returning: result) }
            }
            store.execute(query)
        }
    }
}
