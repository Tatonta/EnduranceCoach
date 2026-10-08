import SwiftUI

struct ReviewView: View {
    @EnvironmentObject private var store: CoachStore
    var body: some View {
        NavigationStack {
            List {
                if let review = store.review {
                    Section("Ultima seduta") {
                        Text(review.verdict).font(.headline)
                        if let workout = review.lastWorkout {
                            Text(workout.name).font(.title2.bold())
                            Text("\(workout.date) · \(workout.source)").foregroundStyle(.secondary)
                            LabeledContent("Distanza", value: workout.distanceKnown == false ? "Non indicata" : String(format: "%.2f km", workout.distanceM / 1000))
                            LabeledContent("Durata", value: Metric.duration(workout.durationS))
                            LabeledContent("Passo medio", value: Metric.pace(workout.avgPaceSKm))
                            LabeledContent("FC media", value: workout.avgHr.map { "\(Int($0.rounded())) bpm" } ?? "Non disponibile")
                            LabeledContent("Dislivello positivo", value: workout.elevationGainM.map { "\(Int($0.rounded())) m" } ?? "Non disponibile")
                            if let feedback = workout.feedback {
                                Text("Feedback dichiarato dall'atleta; non sono misure dell'orologio.").font(.footnote).foregroundStyle(.secondary)
                                LabeledContent("Sforzo percepito", value: feedback.perceivedExertion.map { "\($0)/10" } ?? "Non indicato")
                                LabeledContent("Sensazioni", value: FeedbackText.feeling(feedback.feeling))
                                LabeledContent("Fastidi/dolore", value: FeedbackText.discomfort(feedback.discomfort))
                                if !feedback.notes.isEmpty { Text(feedback.notes) }
                            }
                        } else { Text("Importa i workout da Account per ottenere la prima review.") }
                    }
                    if let match = review.match {
                        Section("Confronto con il piano") {
                            Text(match.plannedName ?? "Seduta prevista")
                            Text(statusText(match.status)).foregroundStyle(.secondary)
                            if let note = match.note { Text(note) }
                        }
                    }
                    if let detailed = review.detailedReview, review.lastWorkout?.source != "manual" {
                        DetailedReviewSections(detail: detailed, sport: review.lastWorkout?.sport ?? "running")
                    }
                    Section("Programma") { Text(review.program.reason) }
                    Section("Dati della review") {
                        Text("Versione piano \(review.planVersion)")
                        Text("Calcolata: \(review.generatedAt)").font(.caption).foregroundStyle(.secondary)
                        if !store.reviewIsCurrent { Text("La review precedente è visualizzata per riferimento. Aggiorna prima di prendere decisioni.").foregroundStyle(.orange) }
                    }
                } else {
                    Section {
                        ContentUnavailableView(store.plan == nil ? "Aggiungi il tuo piano" : "Review da caricare",
                            systemImage: "figure.run", description: Text(store.plan == nil ? "Apri Piano e importa il programma JSON." : "Aggiorna per leggere l'ultima seduta."))
                    }
                }
                if store.busy { ProgressView("Aggiornamento…") }
            }
            .navigationTitle("Review")
            .refreshable { await store.run { try await store.refresh() } }
            .toolbar { Button("Aggiorna", systemImage: "arrow.clockwise") { Task { await store.run { try await store.refresh() } } }.disabled(store.busy) }
        }
    }
    private func statusText(_ status: String) -> String {
        switch status {
        case "completed": return "Completata"
        case "completed_modified": return "Completata con durata diversa"
        case "substituted": return "Alternativa svolta"
        default: return status
        }
    }
}

struct AdviceView: View {
    @EnvironmentObject private var store: CoachStore
    var body: some View {
        NavigationStack {
            List {
                if let review = store.review {
                    Section("Per la prossima seduta") {
                        ForEach(Array(review.advice.enumerated()), id: \.offset) { _, advice in Text(advice) }
                        if review.advice.isEmpty { Text("Importa la prima attività per ricevere consigli sul recupero e sulla prossima seduta.") }
                    }
                    Section("Adattare il programma?") {
                        Label(review.program.eligible ? "Valuta un piccolo adattamento" : "Mantieni il piano", systemImage: review.program.eligible ? "arrow.triangle.branch" : "checkmark.circle")
                            .font(.headline)
                        Text(review.program.reason)
                        TimelineView(.periodic(from: .now, by: 1)) { _ in
                            if store.canOfferAdjustment {
                                Button("Vedi la proposta") { Task { await store.run { try await store.previewAdjustment() } } }
                                    .accessibilityIdentifier("preview-adjustment")
                            } else if review.program.eligible {
                                Text("Aggiorna la review per verificare se la proposta è ancora valida.").font(.footnote).foregroundStyle(.secondary)
                            }
                        }
                    }
                    if !review.program.evidence.isEmpty {
                        Section("Corse confrontate") {
                            ForEach(review.program.evidence, id: \.activityId) { evidence in
                                VStack(alignment: .leading) {
                                    Text("\(evidence.date) · \(evidence.name)")
                                    Text("\(Metric.pace(evidence.avgPaceSKm)) · \(Int(evidence.avgHr.rounded())) bpm").foregroundStyle(.secondary)
                                }
                            }
                        }
                    }
                    Section("Criteri e contesto") {
                        Text(review.program.policy)
                        ForEach(Array(review.limitations.enumerated()), id: \.offset) { _, item in Text(item).font(.footnote).foregroundStyle(.secondary) }
                    }
                } else { ContentUnavailableView("Consigli dopo la prima review", systemImage: "lightbulb", description: Text("Aggiungi il piano e importa i workout.")) }
            }.navigationTitle("Consigli")
                .refreshable { await store.run { try await store.refresh() } }
        }
    }
}

struct AdjustmentSheet: View {
    @EnvironmentObject private var store: CoachStore
    @Environment(\.dismiss) private var dismiss
    @State private var confirmed = false
    let proposal: AdjustmentProposal
    var body: some View {
        NavigationStack {
            List {
                Section("Motivo") { Text(proposal.reason) }
                Section("Modifiche precise") {
                    ForEach(proposal.changes) { change in
                        VStack(alignment: .leading, spacing: 8) {
                            Text("\(change.date) · \(change.name)").font(.headline)
                            Text(String(format: "Durata prevista: %.1f → %.1f min", change.beforeDurationMin, change.afterDurationMin))
                            Text(change.description)
                            ForEach(Array(change.stepChanges.enumerated()), id: \.offset) { _, step in
                                Text("\(step.type) ×\(step.iterations): \(Int(step.beforeDurationS)) → \(Int(step.afterDurationS)) secondi per tratto").font(.footnote)
                            }
                        }.padding(.vertical, 4)
                    }
                }
                Section {
                    Text("Piano di partenza: versione \(proposal.baseVersion). Anteprima valida fino a \(proposal.expiresAt).")
                        .font(.footnote).foregroundStyle(.secondary)
                    Text("L'app aggiorna il programma sul servizio. L'invio dei workout all'orologio non è disponibile.")
                    Toggle("Ho controllato le modifiche e il contesto delle corse", isOn: $confirmed)
                    TimelineView(.periodic(from: .now, by: 1)) { _ in
                        let expired = (Wire.date(proposal.expiresAt) ?? .distantPast) <= Date()
                        Button("Conferma e aggiorna il piano") { Task { await store.run { try await store.applyAdjustment(proposal) } } }
                            .disabled(!confirmed || store.busy || expired)
                            .accessibilityIdentifier("apply-adjustment")
                        if expired { Text("Anteprima scaduta. Chiudi e aggiorna la review.").foregroundStyle(.orange) }
                    }
                }
            }.navigationTitle("Proposta di adattamento").navigationBarTitleDisplayMode(.inline)
                .toolbar { Button("Chiudi") { dismiss() }.disabled(store.busy) }
                .interactiveDismissDisabled(store.busy)
        }
    }
}
