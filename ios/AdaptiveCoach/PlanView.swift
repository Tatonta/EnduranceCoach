import SwiftUI
import UniformTypeIdentifiers

struct PlanView: View {
    @EnvironmentObject private var store: CoachStore
    @State private var pickingFile = false
    @State private var confirming = false
    var body: some View {
        NavigationStack {
            List {
                if let response = store.plan, let plan = try? response.display() {
                    Section {
                        Text(plan.planName).font(.headline)
                        Text(plan.goal)
                        Text("Versione \(response.version)").foregroundStyle(.secondary)
                    }
                    Section("Sedute") {
                        ForEach(plan.workouts, id: \.stableID) { workout in
                            DisclosureGroup("\(workout.date) · \(workout.name)") {
                                Text(workout.description)
                                if let duration = workout.estimatedDurationMin { Text(String(format: "Durata prevista: %.1f min", duration)) }
                                ForEach(Array(workout.steps.enumerated()), id: \.offset) { _, step in
                                    Text(stepDescription(step)).font(.footnote)
                                }
                            }
                        }
                    }
                    if !plan.notes.isEmpty { Section("Note") { ForEach(Array(plan.notes.enumerated()), id: \.offset) { _, note in Text(note) } } }
                } else {
                    Section { Text("Importa il tuo piano JSON. Il servizio valida sedute, date, passi e ripetizioni prima di salvarlo.") }
                }
                Section {
                    Button(store.plan == nil ? "Importa piano JSON" : "Sostituisci piano da JSON") { pickingFile = true }.disabled(store.busy)
                    Text("Le modifiche si applicano solo al programma del tuo account. Il piano precedente resta nella cronologia del servizio.").font(.footnote).foregroundStyle(.secondary)
                }
            }.scrollContentBackground(.hidden).background(CoachTheme.background).navigationTitle("Piano")
                .refreshable { await store.run { try await store.refresh() } }
                .fileImporter(isPresented: $pickingFile, allowedContentTypes: [.json]) { result in
                    Task {
                        await store.run { try store.readPlanFile(result.get()); confirming = true }
                    }
                }
                .sheet(isPresented: $confirming, onDismiss: { store.pendingPlan = nil }) {
                    NavigationStack {
                        List {
                            if let value = store.pendingPlan,
                               let plan = try? Wire.decoder().decode(TrainingPlan.self, from: JSONEncoder().encode(value)) {
                                Text(plan.planName).font(.headline)
                                Text(plan.goal)
                                Text("\(plan.workouts.count) sedute")
                                ForEach(plan.workouts, id: \.stableID) { Text("\($0.date) · \($0.name)") }
                            }
                            Button("Conferma importazione del programma") {
                                Task {
                                    await store.run { try await store.savePendingPlan(); confirming = false }
                                }
                            }.disabled(store.busy || store.pendingPlan == nil)
                        }.scrollContentBackground(.hidden).background(CoachTheme.background).navigationTitle("Controlla il piano")
                            .toolbar { Button("Annulla") { confirming = false }.disabled(store.busy) }
                            .interactiveDismissDisabled(store.busy)
                    }
                }
        }
    }
    private func stepDescription(_ step: PlannedStep) -> String {
        if step.type == "repeat" { return "\(step.iterations ?? 1) ripetizioni: " + step.steps.map(stepDescription).joined(separator: "; ") }
        let duration = step.durationS.map(Metric.duration) ?? step.durationMin.map { Metric.duration($0 * 60) }
        return "\(step.type): " + (duration ?? step.distanceM.map { String(format: "%.0f m", $0) } ?? "")
            + (step.target.map { " · " + $0.description } ?? "")
    }
}
