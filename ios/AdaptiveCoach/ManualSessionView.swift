import SwiftUI

enum FeedbackText {
    static func feeling(_ value: String) -> String {
        ["good": "Buone", "normal": "Normali", "fatigued": "Stanco", "very_fatigued": "Molto stanco"][value] ?? "Non indicate"
    }
    static func discomfort(_ value: String) -> String {
        ["none": "Non segnalati", "present": "Segnalati", "prefer_not_to_say": "Non indicato"][value] ?? "Non indicato"
    }
}

struct ManualSessionView: View {
    @EnvironmentObject private var store: CoachStore
    @Environment(\.dismiss) private var dismiss
    @State private var requestID = UUID().uuidString.lowercased()
    @State private var name = ""
    @State private var sport = "running"
    @State private var start = Date().addingTimeInterval(-3600)
    @State private var minutes = 30.0
    @State private var distance = ""
    @State private var exertion = ""
    @State private var feeling = "normal"
    @State private var discomfort = "prefer_not_to_say"
    @State private var completed = ""
    @State private var notes = ""
    var body: some View {
        NavigationStack {
            Form {
                Section("Seduta conclusa") {
                    Text("Per una seduta non già importata dall'orologio. Puoi lasciare vuote le metriche che non conosci.").font(.footnote)
                    TextField("Nome della seduta", text: $name)
                    Picker("Sport", selection: $sport) {
                        Text("Corsa").tag("running"); Text("Bici").tag("cycling")
                        Text("Palestra / forza").tag("strength"); Text("Altro").tag("other")
                    }
                    DatePicker("Inizio", selection: $start, in: ...Date())
                    TextField("Durata in minuti", value: $minutes, format: .number).keyboardType(.decimalPad)
                    TextField("Distanza in km (facoltativa)", text: $distance).keyboardType(.decimalPad)
                }
                Section("Come l'hai vissuta?") {
                    TextField("Sforzo percepito 1–10 (facoltativo)", text: $exertion).keyboardType(.numberPad)
                    Text("1 = molto facile, 10 = massimo sforzo percepito. È una tua valutazione, non una misura fisiologica.").font(.footnote).foregroundStyle(.secondary)
                    Picker("Sensazioni", selection: $feeling) {
                        Text("Buone").tag("good"); Text("Normali").tag("normal")
                        Text("Stanco").tag("fatigued"); Text("Molto stanco").tag("very_fatigued")
                    }
                    Picker("Fastidi o dolore", selection: $discomfort) {
                        Text("Non voglio indicarlo").tag("prefer_not_to_say")
                        Text("Non ne ho avuti").tag("none"); Text("Ne ho avuti").tag("present")
                    }
                    Picker("Come previsto?", selection: $completed) {
                        Text("Non so / non avevo un piano").tag("")
                        Text("Sì").tag("true"); Text("Ho modificato o interrotto").tag("false")
                    }
                    TextField("Note per il coach", text: $notes, axis: .vertical).lineLimit(3...6)
                }
                Section {
                    Text("Invii durata e feedback al servizio di coaching configurato. Una seduta dichiarata non abilita da sola il cambio automatico del programma.").font(.footnote)
                    Button("Salva il feedback") { save() }.disabled(store.busy || name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    if store.busy { ProgressView("Salvataggio…") }
                }
            }.navigationTitle("Com'è andata?")
                .toolbar { Button("Annulla") { dismiss() }.disabled(store.busy) }
                .interactiveDismissDisabled(store.busy)
        }
    }
    private func save() {
        do {
            let trimmedDistance = distance.trimmingCharacters(in: .whitespacesAndNewlines)
            let km = trimmedDistance.isEmpty ? nil : Double(trimmedDistance.replacingOccurrences(of: ",", with: "."))
            let trimmedExertion = exertion.trimmingCharacters(in: .whitespacesAndNewlines)
            let rpe = trimmedExertion.isEmpty ? nil : Int(trimmedExertion)
            guard minutes.isFinite, 1...1440 ~= minutes, (trimmedDistance.isEmpty || (km.map { $0.isFinite && 0...1500 ~= $0 } ?? false)),
                  (trimmedExertion.isEmpty || (rpe.map { 1...10 ~= $0 } ?? false)), name.count <= 100, notes.count <= 1500 else {
                throw ServiceError(status: 0, code: "manual_value", message: "Controlla nome, durata, distanza, sforzo 1–10 e lunghezza delle note.")
            }
            let value = ManualSessionRequest(requestId: requestID, name: name, sport: sport, startTime: Wire.iso(start), durationMin: minutes,
                distanceKm: km, perceivedExertion: rpe, feeling: feeling, discomfort: discomfort,
                completedAsPlanned: completed.isEmpty ? nil : completed == "true", notes: notes)
            Task { await store.run { try await store.saveManualSession(value); dismiss() } }
        } catch { store.errorMessage = error.localizedDescription }
    }
}
