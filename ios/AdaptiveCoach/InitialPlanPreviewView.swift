import SwiftUI

struct InitialPlanPreviewView: View {
    @EnvironmentObject private var store: CoachStore
    @Environment(\.dismiss) private var dismiss
    @ObservedObject var connection: ChatGPTConnection
    let draft: InitialPlanDraft
    @State private var confirmed = false

    var body: some View {
        NavigationStack {
            List {
                Section("Le tue prime sedute · bozza") {
                    Text(draft.preview.explanation)
                    Text("Controlla giorni, durata e recupero. La bozza scade dopo 15 minuti e non sostituisce un programma esistente.").font(.footnote).foregroundStyle(.secondary)
                }
                if let plan = try? PlanReply(version: 0, plan: draft.preview.plan).display() {
                    ForEach(plan.workouts, id: \.stableID) { workout in
                        Section(workout.name) {
                            Text(workout.date + " · " + sport(workout.sport))
                            if let minutes = workout.estimatedDurationMin { Text("\(minutes, specifier: "%.1f") minuti totali") }
                            Text(workout.description)
                            ForEach(Array(workout.steps.enumerated()), id: \.offset) { _, step in
                                Text("\(label(step.type)): \((step.durationMin ?? (step.durationS ?? 0) / 60), specifier: "%.1f") min")
                            }
                        }
                    }
                }
                Section {
                    Toggle("Ho esaminato le sedute e confermo il programma iniziale", isOn: $confirmed).disabled(store.busy)
                    TimelineView(.periodic(from: .now, by: 10)) { timeline in
                        let current = draft.isCurrent(owner: store.identity?.id, generation: connection.accountGeneration,
                                                      selectedClient: connection.selectedRegistrationID, now: timeline.date)
                        if !current { Text("Bozza scaduta o account cambiato. Preparane una nuova.").foregroundStyle(.orange) }
                        Button("Salva il programma iniziale") {
                            Task {
                                await store.run {
                                    guard confirmed, draft.isCurrent(owner: store.identity?.id, generation: connection.accountGeneration,
                                                                     selectedClient: connection.selectedRegistrationID) else {
                                        throw ServiceError(status: 409, code: "initial_draft_stale", message: "Bozza scaduta o account cambiato.")
                                    }
                                    try await store.applyInitialPlan(draft.preview)
                                    dismiss()
                                }
                            }
                        }.disabled(!confirmed || !current || store.busy)
                    }
                    Text("Il programma viene salvato se profilo e storico sono ancora aggiornati e non esiste un piano. Le sedute saranno disponibili nell'app; l'invio ai dispositivi non è ancora disponibile.").font(.footnote).foregroundStyle(.secondary)
                }
            }
            .scrollContentBackground(.hidden).background(CoachTheme.background)
            .navigationTitle("Anteprima del programma")
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Chiudi") { dismiss() }.disabled(store.busy) } }
        }
    }
    private func label(_ type: String) -> String {
        ["warmup": "Riscaldamento", "run": "Fase centrale", "cooldown": "Defaticamento"][type] ?? type
    }
    private func sport(_ type: String) -> String {
        ["running": "Corsa", "cycling": "Ciclismo", "rest": "Riposo", "manual": "Forza / palestra"][type] ?? "Allenamento"
    }
}
