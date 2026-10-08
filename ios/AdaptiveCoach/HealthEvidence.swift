import Foundation

enum HealthMetric: String, CaseIterable { case heart, speed, stride, groundContact, vertical, power, cadence, steps, distance }
struct HealthReading { let start: Double; let end: Double; let value: Double }
struct HealthInterval { let start: Double; let end: Double }
struct HealthCoordinate { let time: Double; let lat: Double; let lon: Double; let accuracy: Double }
struct EvidenceDynamics: Encodable {
    var cadenceSpm: Double? = nil
    var cadenceRpm: Double? = nil
    var strideM: Double? = nil
    var groundContactS: Double? = nil
    var verticalOscillationM: Double? = nil
    var powerW: Double? = nil
}
struct EvidenceSample: Encodable {
    let elapsedS: Double
    var hr: Double? = nil
    var speedMetersPerSecond: Double? = nil
    var strideM: Double? = nil
    var groundContactS: Double? = nil
    var verticalOscillationM: Double? = nil
    var cadenceRpm: Double? = nil
    var cadenceSpm: Double? = nil
    var powerW: Double? = nil
    let segment: Int
    enum CodingKeys: String, CodingKey {
        case elapsedS, hr, strideM, groundContactS, verticalOscillationM, cadenceRpm, cadenceSpm, powerW, segment
        case speedMetersPerSecond = "speed_m_s"
    }
}
struct EvidenceLap: Encodable {
    let lap: Int
    let phaseType = "unknown"
    let startElapsedS: Double
    let durationS: Double
    let elapsedS: Double
    let distanceM: Double?
    let avgHr: Double?
    let maxHr: Double?
    let strideM: Double?
    let groundContactS: Double?
    let verticalOscillationM: Double?
    let cadenceRpm: Double?
    let cadenceSpm: Double?
    let powerW: Double?
}
struct EvidenceRoutePoint: Encodable { let lat: Double; let lon: Double }
struct HealthEvidence: Encodable {
    let schemaVersion = 1
    var laps: [EvidenceLap]
    let samples: [EvidenceSample]
    var routeSegments: [[EvidenceRoutePoint]]
    let dynamics: EvidenceDynamics
    let reportedSampleCount: Int
    var coverageNote: String
    var hasEvidence: Bool { !laps.isEmpty || !samples.isEmpty || !routeSegments.isEmpty }
}
struct HealthDetailCandidate: Identifiable {
    var id: String { activity.id }
    let activity: ImportedActivity
    let evidence: HealthEvidence
    let rawRouteCount: Int
}
struct HealthDetailWrite: Encodable {
    let expectedDetailsVersion: Int
    let expectedActivityHash: String
    let details: HealthEvidence
}

enum HealthEvidenceBuilder {
    static func build(readings input: [HealthMetric: [HealthReading]], elapsed: Double, active: Double,
                      lapIntervals: [HealthInterval], pauses: [HealthInterval], routes: [[HealthCoordinate]], cycling: Bool) -> HealthEvidence {
        var readings = input.mapValues { rows in rows.filter { $0.start.isFinite && $0.end.isFinite && $0.value.isFinite && $0.start >= 0 && $0.end >= $0.start && $0.end <= elapsed + 1 }.sorted { $0.start < $1.start } }
        if !cycling {
            readings[.cadence] = (readings[.steps] ?? []).compactMap { row in
                guard row.end > row.start, !pauses.contains(where: { $0.start < row.end && $0.end > row.start }) else { return nil }
                return HealthReading(start: row.start, end: row.end, value: row.value * 60 / (row.end - row.start))
            }
        }
        let clocks = Set(readings.filter { $0.key != .distance && $0.key != .steps }.values.flatMap { $0.map { ($0.start + $0.end) / 2 } }).sorted()
        var cursors: [HealthMetric: Int] = [:], samples: [EvidenceSample] = [], group = 0, previous: Double? = nil
        let stride = max(1, Int(ceil(Double(clocks.count) / 4000)))
        for (index, time) in clocks.enumerated() {
            if let previous, time - previous > 30 || pauses.contains(where: { $0.start >= previous && $0.end <= time }) { group += 1 }
            previous = time
            // Advance all cursors even when the output is reduced; do not invent interpolated quantities.
            var values: [HealthMetric: Double] = [:]
            for metric in HealthMetric.allCases where metric != .distance && metric != .steps {
                let rows = readings[metric] ?? []; var cursor = cursors[metric] ?? 0
                while cursor < rows.count && rows[cursor].end < time { cursor += 1 }
                cursors[metric] = cursor
                if cursor < rows.count, rows[cursor].start <= time && rows[cursor].end >= time,
                   valid(rows[cursor].value, metric: metric) { values[metric] = rows[cursor].value }
            }
            if index % stride != 0 || values.isEmpty { continue }
            var point = EvidenceSample(elapsedS: time, segment: group)
            point.hr = values[.heart]; point.speedMetersPerSecond = values[.speed]; point.powerW = values[.power]
            if cycling { point.cadenceRpm = values[.cadence] }
            else { point.cadenceSpm = values[.cadence]; point.strideM = values[.stride]; point.groundContactS = values[.groundContact]; point.verticalOscillationM = values[.vertical] }
            samples.append(point)
        }
        var dynamics = EvidenceDynamics()
        dynamics.powerW = average(readings[.power] ?? [], metric: .power)
        if cycling { dynamics.cadenceRpm = average(readings[.cadence] ?? [], metric: .cadence) }
        else {
            dynamics.cadenceSpm = average(readings[.cadence] ?? [], metric: .cadence)
            dynamics.strideM = average(readings[.stride] ?? [], metric: .stride)
            dynamics.groundContactS = average(readings[.groundContact] ?? [], metric: .groundContact)
            dynamics.verticalOscillationM = average(readings[.vertical] ?? [], metric: .vertical)
        }
        var laps: [EvidenceLap] = []
        let pauseDuration = pauses.reduce(0.0) { $0 + max(0, $1.end - $1.start) }
        let verifiedActive = abs(elapsed - pauseDuration - active) <= 1
        for interval in lapIntervals where verifiedActive && laps.count < 500 {
            let paused = pauses.reduce(0.0) { $0 + max(0, min(interval.end, $1.end) - max(interval.start, $1.start)) }
            let duration = interval.end - interval.start - paused
            guard duration > 0, interval.start >= 0, interval.end <= elapsed else { continue }
            func contained(_ metric: HealthMetric) -> [HealthReading] { (readings[metric] ?? []).filter { row in
                row.start >= interval.start && row.end <= interval.end && (metric == .distance || !pauses.contains { pause in row.start < pause.end && row.end > pause.start })
            } }
            let distances = contained(.distance)
            let ambiguousDistance = distances.contains { row in row.value > 0 && pauses.contains { $0.start < row.end && $0.end > row.start } }
            let heart = contained(.heart).filter { valid($0.value, metric: .heart) }
            laps.append(EvidenceLap(lap: laps.count + 1, startElapsedS: interval.start, durationS: duration,
                elapsedS: interval.end - interval.start, distanceM: ambiguousDistance ? nil : completeDistance(distances, interval),
                avgHr: average(heart, metric: .heart), maxHr: heart.map(\.value).max(),
                strideM: cycling ? nil : average(contained(.stride), metric: .stride),
                groundContactS: cycling ? nil : average(contained(.groundContact), metric: .groundContact),
                verticalOscillationM: cycling ? nil : average(contained(.vertical), metric: .vertical),
                cadenceRpm: cycling ? average(contained(.cadence), metric: .cadence) : nil,
                cadenceSpm: cycling ? nil : average(contained(.cadence), metric: .cadence),
                powerW: average(contained(.power), metric: .power)))
        }
        let segments = routeSegments(routes, elapsed: elapsed)
        let notes = "Campioni del workout, combinati solo in finestre misurate. Distanza lap assente se incompleta. Fasi/target non dedotti. Cadenza corsa derivata dai passi nelle finestre senza pause. GPS ridotto con buchi separati."
            + (verifiedActive ? "" : " Tempi attivi dei lap non verificabili: lap omessi.")
        return HealthEvidence(laps: laps, samples: samples, routeSegments: segments, dynamics: dynamics,
                              reportedSampleCount: clocks.count, coverageNote: notes)
    }
    private static func valid(_ value: Double, metric: HealthMetric) -> Bool {
        switch metric {
        case .heart: return value > 0 && value <= 250
        case .speed: return value >= 0 && value <= 40
        case .stride: return value > 0 && value <= 5
        case .groundContact: return value > 0 && value <= 2
        case .vertical: return value >= 0 && value <= 0.5
        case .power: return value >= 0 && value <= 4000
        case .cadence: return value >= 0 && value <= 300
        case .steps: return value >= 0
        case .distance: return value >= 0
        }
    }
    private static func average(_ rows: [HealthReading], metric: HealthMetric) -> Double? {
        let validRows = rows.filter { valid($0.value, metric: metric) }
        let weight = validRows.reduce(0.0) { $0 + max(0.001, $1.end - $1.start) }
        return weight > 0 ? validRows.reduce(0.0) { $0 + $1.value * max(0.001, $1.end - $1.start) } / weight : nil
    }
    private static func completeDistance(_ rows: [HealthReading], _ interval: HealthInterval) -> Double? {
        let sorted = rows.filter { valid($0.value, metric: .distance) }.sorted { $0.start < $1.start }
        var end = interval.start, sum = 0.0
        for row in sorted {
            guard abs(row.start - end) <= 1 else { return nil }
            end = row.end; sum += row.value
        }
        return !sorted.isEmpty && abs(end - interval.end) <= 1 ? sum : nil
    }
    static func totalDistance(_ rows: [HealthReading], elapsed: Double) -> Double? {
        completeDistance(rows, HealthInterval(start: 0, end: elapsed))
    }
    private static func routeSegments(_ routes: [[HealthCoordinate]], elapsed: Double) -> [[EvidenceRoutePoint]] {
        var segments: [[EvidenceRoutePoint]] = []
        for route in routes {
            var current: [EvidenceRoutePoint] = [], previous: Double? = nil
            for point in route {
                let good = point.lat.isFinite && point.lon.isFinite && point.time >= 0 && point.time <= elapsed && point.accuracy >= 0 && point.accuracy <= 60 && abs(point.lat) <= 90 && abs(point.lon) <= 180
                if !good || (previous.map { point.time <= $0 || point.time - $0 > 30 } ?? false) {
                    if current.count >= 2 { segments.append(current) }; current = []
                }
                if good { current.append(EvidenceRoutePoint(lat: point.lat, lon: point.lon)); previous = point.time }
                else { previous = nil }
            }
            if current.count >= 2 { segments.append(current) }
        }
        segments = Array(segments.prefix(100))
        let total = segments.reduce(0) { $0 + $1.count }
        let stride = max(1, Int(ceil(Double(total) / Double(max(1, 2000 - segments.count * 2)))))
        return segments.map { segment in
            var points = segment.enumerated().compactMap { $0.offset % stride == 0 ? $0.element : nil }
            if let last = segment.last, let kept = points.last, last.lat != kept.lat || last.lon != kept.lon { points.append(last) }
            return points
        }.filter { $0.count >= 2 }
    }
}
