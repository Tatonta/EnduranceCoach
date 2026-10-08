import Foundation
import HealthKit
import CoreLocation

@MainActor
final class HealthImporter {
    // Do not open a HealthKit connection at launch; wait for the explicit import action.
    private lazy var store = HKHealthStore()
    private let heart = HKQuantityType(.heartRate)
    private let runningDistance = HKQuantityType(.distanceWalkingRunning)
    private let cyclingDistance = HKQuantityType(.distanceCycling)

    func previewDetails(_ activity: ImportedActivity, includeRoute: Bool) async throws -> HealthDetailCandidate {
        guard activity.source == "apple_health", ["running", "cycling"].contains(activity.sport), let uuid = UUID(uuidString: activity.sourceActivityId) else {
            throw ServiceError(status: 0, code: "health_detail_source", message: "Seleziona un workout di corsa o bici Apple Health.")
        }
        let cycling = activity.sport == "cycling"
        let specifications: [(HealthMetric, HKQuantityType, HKUnit)] = cycling ? [
            (.heart, heart, .count().unitDivided(by: .minute())),
            (.speed, HKQuantityType(.cyclingSpeed), .meter().unitDivided(by: .second())),
            (.power, HKQuantityType(.cyclingPower), .watt()),
            (.cadence, HKQuantityType(.cyclingCadence), .count().unitDivided(by: .minute())),
            (.distance, cyclingDistance, .meter())
        ] : [
            (.heart, heart, .count().unitDivided(by: .minute())),
            (.speed, HKQuantityType(.runningSpeed), .meter().unitDivided(by: .second())),
            (.stride, HKQuantityType(.runningStrideLength), .meter()),
            (.groundContact, HKQuantityType(.runningGroundContactTime), .second()),
            (.vertical, HKQuantityType(.runningVerticalOscillation), .meter()),
            (.power, HKQuantityType(.runningPower), .watt()),
            (.steps, HKQuantityType(.stepCount), .count()),
            (.distance, runningDistance, .meter())
        ]
        var types = Set<HKObjectType>(specifications.map { $0.1 }); types.insert(HKObjectType.workoutType())
        if includeRoute { types.insert(HKSeriesType.workoutRoute()) }
        try await store.requestAuthorization(toShare: [], read: types)
        let workout: HKWorkout = try await withCheckedThrowingContinuation { continuation in
            store.execute(HKSampleQuery(sampleType: HKObjectType.workoutType(), predicate: HKQuery.predicateForObject(with: uuid), limit: 1, sortDescriptors: nil) { _, values, error in
                if let error { continuation.resume(throwing: error) }
                else if let workout = values?.first as? HKWorkout { continuation.resume(returning: workout) }
                else { continuation.resume(throwing: ServiceError(status: 0, code: "health_detail_unavailable", message: "Workout non leggibile. Può mancare il dato o il permesso di lettura.")) }
            })
        }
        guard workout.endDate <= Date(), workout.duration > 0 else {
            throw ServiceError(status: 0, code: "health_detail_unavailable", message: "Leggi i dettagli di una seduta conclusa.")
        }
        var readings: [HealthMetric: [HealthReading]] = [:]
        for (metric, type, unit) in specifications {
            readings[metric] = try await quantityReadings(type, unit: unit, workout: workout)
        }
        let elapsed = workout.endDate.timeIntervalSince(workout.startDate)
        let intervals = workoutIntervals(workout)
        var routes: [[HealthCoordinate]] = []
        if includeRoute { routes = try await routeReadings(workout) }
        let evidence = HealthEvidenceBuilder.build(readings: readings, elapsed: elapsed, active: workout.duration,
            lapIntervals: intervals.laps, pauses: intervals.pauses, routes: routes, cycling: cycling)
        guard evidence.hasEvidence else {
            throw ServiceError(status: 0, code: "health_detail_unavailable", message: "Nessun lap, campione o percorso leggibile per questa seduta. Puoi importare il riepilogo; le dinamiche potrebbero non essere esportate dall'app dell'orologio.")
        }
        let quantity = cycling ? cyclingDistance : runningDistance
        let distance = workout.statistics(for: quantity)?.sumQuantity()?.doubleValue(for: .meter()) ?? HealthEvidenceBuilder.totalDistance(readings[.distance] ?? [], elapsed: elapsed) ?? activity.distanceM
        let statistics = try await heartStatistics(workout)
        let heartUnit = HKUnit.count().unitDivided(by: .minute())
        let refreshed = ImportedActivity(source: activity.source, sourceActivityId: activity.sourceActivityId, name: activity.name,
            sport: activity.sport, activityType: activity.activityType, startTime: Wire.iso(workout.startDate),
            distanceM: max(0, distance), durationS: workout.duration, elapsedDurationS: max(elapsed, workout.duration),
            avgPaceSKm: !cycling && distance > 0 ? workout.duration / (distance / 1000) : nil,
            avgHr: validHeartRate(statistics?.averageQuantity()?.doubleValue(for: heartUnit)),
            maxHr: validHeartRate(statistics?.maximumQuantity()?.doubleValue(for: heartUnit)),
            elevationGainM: activity.elevationGainM, trainingLoad: nil, aerobicTrainingEffect: nil, workoutId: "")
        return HealthDetailCandidate(activity: refreshed, evidence: evidence, rawRouteCount: routes.reduce(0) { $0 + $1.count })
    }

    private func quantityReadings(_ type: HKQuantityType, unit: HKUnit, workout: HKWorkout) async throws -> [HealthReading] {
        let values: [HKQuantitySample] = try await withCheckedThrowingContinuation { continuation in
            store.execute(HKSampleQuery(sampleType: type, predicate: HKQuery.predicateForObjects(from: workout), limit: 20001,
                sortDescriptors: [NSSortDescriptor(key: HKSampleSortIdentifierStartDate, ascending: true)]) { _, samples, error in
                if let error = error as? HKError, error.code == .errorNoData { continuation.resume(returning: []) }
                else if let error { continuation.resume(throwing: error) }
                else { continuation.resume(returning: (samples ?? []).compactMap { $0 as? HKQuantitySample }) }
            })
        }
        guard values.count <= 20000 else { throw ServiceError(status: 0, code: "health_detail_limit", message: "Oltre 20.000 campioni per metrica: lettura dettagliata interrotta per evitare una copertura presentata come completa.") }
        return values.compactMap { value in
            guard value.startDate >= workout.startDate.addingTimeInterval(-1), value.endDate <= workout.endDate.addingTimeInterval(1) else { return nil }
            let start = max(0, value.startDate.timeIntervalSince(workout.startDate))
            let end = min(workout.endDate.timeIntervalSince(workout.startDate), value.endDate.timeIntervalSince(workout.startDate))
            let number = value.quantity.doubleValue(for: unit)
            guard number.isFinite, end >= start else { return nil }
            return HealthReading(start: start, end: end, value: number)
        }
    }

    private func workoutIntervals(_ workout: HKWorkout) -> (laps: [HealthInterval], pauses: [HealthInterval]) {
        let elapsed = workout.endDate.timeIntervalSince(workout.startDate)
        let events = (workout.workoutEvents ?? []).sorted { $0.dateInterval.start < $1.dateInterval.start }
        var pauseStart: Double? = nil, pauses: [HealthInterval] = []
        for event in events {
            let time = max(0, min(elapsed, event.dateInterval.start.timeIntervalSince(workout.startDate)))
            if event.type == .pause || event.type == .motionPaused { if pauseStart == nil { pauseStart = time } }
            if event.type == .resume || event.type == .motionResumed, let began = pauseStart { pauses.append(HealthInterval(start: began, end: time)); pauseStart = nil }
        }
        if let began = pauseStart { pauses.append(HealthInterval(start: began, end: elapsed)) }
        let boundaries = Array(Set(events.filter { $0.type == .lap }.map { $0.dateInterval.end.timeIntervalSince(workout.startDate) }.filter { $0 > 0 && $0 <= elapsed })).sorted()
        var laps: [HealthInterval] = []
        if !boundaries.isEmpty {
            var start = 0.0
            for end in boundaries { laps.append(HealthInterval(start: start, end: end)); start = end }
            if start < elapsed { laps.append(HealthInterval(start: start, end: elapsed)) }
        } else {
            for event in events where event.type == .segment {
                let start = event.dateInterval.start.timeIntervalSince(workout.startDate), end = event.dateInterval.end.timeIntervalSince(workout.startDate)
                if start >= 0 && end > start && end <= elapsed && (laps.last.map { start >= $0.end } ?? true) { laps.append(HealthInterval(start: start, end: end)) }
            }
        }
        return (Array(laps.prefix(500)), pauses)
    }

    private func routeReadings(_ workout: HKWorkout) async throws -> [[HealthCoordinate]] {
        let routes: [HKWorkoutRoute] = try await withCheckedThrowingContinuation { continuation in
            store.execute(HKSampleQuery(sampleType: HKSeriesType.workoutRoute(), predicate: HKQuery.predicateForObjects(from: workout), limit: 101, sortDescriptors: nil) { _, values, error in
                if let error { continuation.resume(throwing: error) }
                else { continuation.resume(returning: (values ?? []).compactMap { $0 as? HKWorkoutRoute }) }
            })
        }
        guard routes.count <= 100 else { throw ServiceError(status: 0, code: "health_route_limit", message: "Troppi segmenti di percorso: lettura interrotta.") }
        var result: [[HealthCoordinate]] = []
        var totalPoints = 0
        for route in routes {
            let points: [HealthCoordinate] = try await withCheckedThrowingContinuation { continuation in
                let collector = HealthRouteCollector(start: workout.startDate)
                let query = HKWorkoutRouteQuery(route: route) { query, locations, done, error in
                    if let outcome = collector.receive(locations ?? [], done: done, error: error) {
                        continuation.resume(with: outcome)
                        if case .failure = outcome { Task { @MainActor in self.store.stop(query) } }
                    }
                }
                store.execute(query)
            }
            totalPoints += points.count
            guard totalPoints <= 50000 else { throw ServiceError(status: 0, code: "health_route_limit", message: "Oltre 50.000 punti GPS complessivi: lettura interrotta.") }
            result.append(points)
        }
        return result
    }

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

private final class HealthRouteCollector: @unchecked Sendable {
    private let lock = NSLock()
    private let start: Date
    private var points: [HealthCoordinate] = []
    private var finished = false
    init(start: Date) { self.start = start }
    func receive(_ locations: [CLLocation], done: Bool, error: Error?) -> Result<[HealthCoordinate], Error>? {
        lock.lock(); defer { lock.unlock() }
        guard !finished else { return nil }
        if let error { finished = true; return .failure(error) }
        if points.count + locations.count > 50000 {
            finished = true
            return .failure(ServiceError(status: 0, code: "health_route_limit", message: "Oltre 50.000 punti GPS: lettura interrotta."))
        }
        points.append(contentsOf: locations.map { HealthCoordinate(time: $0.timestamp.timeIntervalSince(start), lat: $0.coordinate.latitude, lon: $0.coordinate.longitude, accuracy: $0.horizontalAccuracy) })
        if done { finished = true; return .success(points) }
        return nil
    }
}
