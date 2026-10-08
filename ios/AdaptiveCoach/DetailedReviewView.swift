import SwiftUI
import Charts
import MapKit

struct DetailedReviewSections: View {
    let detail: DetailedReview
    let sport: String
    var body: some View {
        if let analysis = detail.analysis, detail.status == "ready" {
            Section("Analisi della seduta · \(detail.source)") {
                Text(analysis.verdict).font(.headline)
                if let version = detail.planReference?.version { Text("Target dal piano riferito, versione \(version). Collegamento dichiarato dal client.").font(.footnote).foregroundStyle(.secondary) }
                ForEach(Array(analysis.positive.enumerated()), id: \.offset) { _, item in Label(item, systemImage: "checkmark.circle").foregroundStyle(.green) }
                ForEach(Array(analysis.issues.enumerated()), id: \.offset) { _, item in Label(item, systemImage: "exclamationmark.circle").foregroundStyle(.orange) }
                ForEach(Array(analysis.actions.enumerated()), id: \.offset) { _, item in Text(item) }
            }
            Section("Fasi registrate") {
                if analysis.phases.isEmpty { Text("Nessuna fase identificata nei lap forniti.") }
                ForEach(analysis.phases) { phase in PhaseRow(phase: phase, sport: sport) }
            }
            Section(sport == "running" ? "Dinamiche di corsa" : "Metriche della seduta") {
                if sport == "running" {
                    LabeledContent("Cadenza", value: metric(analysis.dynamics.cadenceSpm, "passi/min"))
                    LabeledContent("Stride length", value: metric(analysis.dynamics.strideM, "m", decimals: 2))
                    LabeledContent("Contatto a terra", value: metric(analysis.dynamics.gctMs, "ms"))
                    LabeledContent("Oscillazione verticale", value: metric(analysis.dynamics.verticalCm, "cm"))
                    Text("Non esiste un valore universale ideale di cadenza o lunghezza del passo.").font(.footnote).foregroundStyle(.secondary)
                } else { LabeledContent("Cadenza", value: metric(analysis.dynamics.cadenceRpm, "rpm")) }
                LabeledContent("Potenza", value: metric(analysis.dynamics.powerW, "W"))
            }
            if !analysis.series.isEmpty { Section("Andamento · tempo trascorso") { SessionCharts(samples: analysis.series, running: sport == "running") } }
            if !analysis.routeSegments.isEmpty {
                Section("Percorso registrato") {
                    Map(initialPosition: .automatic) {
                        ForEach(analysis.routeSegments.indices, id: \.self) { index in
                            MapPolyline(coordinates: analysis.routeSegments[index].compactMap { point in
                                guard point.count == 2 else { return nil }
                                return CLLocationCoordinate2D(latitude: point[0], longitude: point[1])
                            }).stroke(.mint, lineWidth: 4)
                        }
                    }.frame(height: 260).accessibilityLabel("Percorso della seduta; segmenti GPS separati")
                    Text("I segmenti separati non vengono uniti attraverso i buchi GPS.").font(.footnote).foregroundStyle(.secondary)
                }
            }
            Section("Lap e copertura") {
                ForEach(analysis.laps) { lap in
                    VStack(alignment: .leading, spacing: 5) {
                        Text("Lap \(lap.lap) · \(lap.phase)").font(.headline)
                        Text("\(Metric.duration(lap.durationS)) · \(sport == "running" ? Metric.pace(lap.paceSKm) : speed(lap.distanceM, lap.durationS))")
                        Text("FC \(metric(lap.avgHr, "bpm")) / max \(metric(lap.maxHr, "bpm"))").font(.footnote)
                        if sport == "running" { Text("Stride \(metric(lap.strideM, "m", decimals: 2)) · cadenza \(metric(lap.cadenceSpm, "passi/min"))").font(.footnote) }
                        ForEach(Array(lap.qualityFlags.enumerated()), id: \.offset) { _, flag in Text(flag).font(.caption).foregroundStyle(.orange) }
                    }
                }
                Text("\(analysis.coverage.lapCount) lap · \(analysis.coverage.sampleCount) campioni forniti · \(analysis.coverage.gpsPoints) punti GPS")
                if let count = analysis.coverage.reportedSampleCount { Text("Copertura originale dichiarata: \(count) campioni").font(.footnote) }
                if !analysis.coverageNote.isEmpty { Text(analysis.coverageNote).font(.footnote) }
                ForEach(Array((detail.limitations ?? []).enumerated()), id: \.offset) { _, item in Text(item).font(.footnote).foregroundStyle(.secondary) }
            }
        } else {
            Section("Dettagli della seduta") {
                Text(detail.status == "stale" ? "Il riepilogo è cambiato. I dettagli precedenti richiedono una nuova lettura dalla fonte." : "La fonte ha fornito il riepilogo, ma non lap e campioni dettagliati.")
                    .foregroundStyle(.secondary)
            }
        }
    }
}

private struct PhaseRow: View {
    let phase: DetailedPhase
    let sport: String
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("\(phase.number). \(phase.name)").font(.headline)
            Text(phase.verdict).foregroundStyle(phase.verdict.contains("troppo") ? Color.orange : Color.secondary)
            Text("\(Metric.duration(phase.durationS)) · \(sport == "running" ? Metric.pace(phase.paceSKm) : speed(phase.distanceM, phase.durationS)) · FC \(metric(phase.avgHr, "bpm"))")
            if let target = phase.target { Text("Target: \(target.description)").font(.footnote) }
            if let planned = phase.plannedDurationS { Text("Previsti \(Metric.duration(planned)) · lap \(phase.lapNumbers.map(String.init).joined(separator: ", "))").font(.footnote) }
            if let difference = phase.hrMeanDifferenceBpm { Text(String(format: "Differenza fra medie lavoro/recupero: %.1f bpm; non è un test clinico di recupero.", difference)).font(.caption).foregroundStyle(.secondary) }
        }.padding(.vertical, 4)
    }
}

private struct SessionCharts: View {
    let samples: [DetailedSample]
    let running: Bool
    private var heartPoints: [SignalPoint] { signal(\.hr) }
    private var pacePoints: [SignalPoint] { signal(\.paceSKm) }
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            if !heartPoints.isEmpty {
                Text("Frequenza cardiaca, bpm").font(.caption)
                Chart(heartPoints) { point in
                    LineMark(x: .value("Minuti", point.elapsedS / 60), y: .value("FC", point.value), series: .value("Segmento", point.segment)).foregroundStyle(.orange)
                }.frame(height: 170)
            }
            if running && !pacePoints.isEmpty {
                Text("Passo dei campioni, min/km").font(.caption)
                Chart(pacePoints) { point in
                    LineMark(x: .value("Minuti", point.elapsedS / 60), y: .value("Passo min/km", point.value / 60), series: .value("Segmento", point.segment)).foregroundStyle(.mint)
                }.frame(height: 170)
            }
        }
    }
    private func signal(_ key: KeyPath<DetailedSample, Double?>) -> [SignalPoint] {
        var result: [SignalPoint] = [], group = 0, previousSegment: Int? = nil
        for sample in samples {
            if previousSegment != nil && previousSegment != sample.segment { group += 1 }
            previousSegment = sample.segment
            guard let value = sample[keyPath: key] else { group += 1; continue }
            result.append(SignalPoint(elapsedS: sample.elapsedS, value: value, segment: group))
        }
        return result
    }
}

private struct SignalPoint: Identifiable {
    var id: Double { elapsedS }
    let elapsedS: Double
    let value: Double
    let segment: Int
}

private func metric(_ value: Double?, _ unit: String, decimals: Int = 1) -> String {
    guard let value else { return "Non disponibile" }
    return String(format: "%.*f %@", decimals, value, unit)
}
private func speed(_ distance: Double?, _ duration: Double) -> String {
    guard let distance, duration > 0 else { return "Velocità non disponibile" }
    return String(format: "%.1f km/h", distance / duration * 3.6)
}
