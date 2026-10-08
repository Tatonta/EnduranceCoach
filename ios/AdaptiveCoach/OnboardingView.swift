import SwiftUI

struct OnboardingView: View {
    @EnvironmentObject private var store: CoachStore
    @Environment(\.dismiss) private var dismiss
    @State private var draft = TrainingProfile()
    @State private var step = 0
    @State private var initialized = false
    @State private var hasDeadline = false
    @State private var deadline = Date().addingTimeInterval(90 * 86400)
    @State private var weight = ""
    @State private var height = ""
    @State private var age = ""
    let editing: Bool
    init(editing: Bool = false) { self.editing = editing }
    private let weekdays = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]
    private let titles = ["Obiettivo", "Profilo", "Esperienza", "Settimana", "Riepilogo"]
    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Text("Partiamo da te.").font(.title2.bold())
                    Text("Il programma deve trovare posto nella tua vita. Puoi ricevere coaching anche senza un orologio.")
                    ProgressView(value: Double(step + 1), total: 5)
                    Text("Passaggio \(step + 1) di 5 · \(titles[step])").font(.caption).foregroundStyle(.secondary)
                }
                switch step {
                case 0: goalSection
                case 1: profileSection
                case 2: experienceSection
                case 3: availabilitySection
                default: summarySection
                }
                Section {
                    if step > 0 { Button("Indietro") { step -= 1 } }
                    if step < 4 { Button("Continua") { validateAndAdvance() } }
                    else { Button("Salva e apri il coach") { save() }.disabled(!draft.coachingConsent || store.busy) }
                    if store.busy { ProgressView("Salvataggio…") }
                }
            }.navigationTitle(editing ? "Profilo e obiettivi" : "Conosciamoci")
                .toolbar {
                    if editing { Button("Chiudi") { dismiss() }.disabled(store.busy) }
                    else { Button("Esci") { Task { await store.run { try await store.logout() } } }.disabled(store.busy) }
                }
                .interactiveDismissDisabled(store.busy)
                .onAppear { loadDraft() }
        }
    }
    private var goalSection: some View {
        Section("Dove vuoi arrivare?") {
            Picker("Sport principale", selection: $draft.primarySport) {
                Text("Corsa").tag("running"); Text("Ciclismo").tag("cycling"); Text("Entrambi").tag("both")
            }
            Picker("Obiettivo", selection: $draft.goalType) {
                Text("Forma e resistenza").tag("fitness"); Text("Continuità").tag("consistency")
                Text("Gara o distanza").tag("event"); Text("Migliorare un tempo").tag("personal_best")
            }
            TextField("Che cosa vuoi ottenere?", text: $draft.goalDescription, axis: .vertical).lineLimit(3...6)
            Toggle("Ho una scadenza", isOn: $hasDeadline)
            if hasDeadline {
                DatePicker("Entro quando", selection: $deadline, in: Date().addingTimeInterval(86400)..., displayedComponents: .date)
                Toggle("Scadenza flessibile", isOn: $draft.deadlineFlexible)
            }
            Text("Il coach considera la data e può suggerire un obiettivo intermedio realistico.").font(.footnote).foregroundStyle(.secondary)
        }
    }
    private var profileSection: some View {
        Section("Profilo e dispositivo") {
            TextField("Età (facoltativa, adulti)", text: $age).keyboardType(.numberPad)
            TextField("Peso in kg (facoltativo)", text: $weight).keyboardType(.decimalPad)
            TextField("Altezza in cm (facoltativa)", text: $height).keyboardType(.decimalPad)
            Picker("Dispositivo", selection: $draft.deviceVendor) {
                Text("Nessun dispositivo").tag("none")
                ForEach(["garmin", "coros", "suunto", "fitbit", "amazfit", "xiaomi", "apple", "other"], id: \.self) { Text($0.capitalized).tag($0) }
            }
            if draft.deviceVendor != "none" { TextField("Modello (facoltativo)", text: $draft.deviceModel) }
            Toggle("Fascia o sensore FC", isOn: $draft.heartRateSensor)
            Toggle("Misuratore di potenza", isOn: $draft.powerMeter)
            Text("Senza dispositivo useremo obiettivi, durata e sensazioni. La scelta del produttore non collega l'account.").font(.footnote).foregroundStyle(.secondary)
        }
    }
    private var experienceSection: some View {
        Group {
            Section("Passato sportivo e base recente") {
                TextField("Anni di corsa", value: $draft.runningYears, format: .number).keyboardType(.decimalPad)
                TextField("Anni di ciclismo", value: $draft.cyclingYears, format: .number).keyboardType(.decimalPad)
                TextField("Corsa, km/settimana recenti", value: $draft.recentRunningKmWeek, format: .number).keyboardType(.decimalPad)
                TextField("Bici, km/settimana recenti", value: $draft.recentCyclingKmWeek, format: .number).keyboardType(.decimalPad)
                TextField("Esperienza, gare e interruzioni", text: $draft.experienceNotes, axis: .vertical).lineLimit(3...6)
            }
            Section("Migliori tempi (facoltativi)") {
                ForEach(draft.bestPerformances.indices, id: \.self) { index in
                    Picker("Sport", selection: $draft.bestPerformances[index].sport) { Text("Corsa").tag("running"); Text("Bici").tag("cycling") }
                    TextField("Distanza in metri", value: $draft.bestPerformances[index].distanceM, format: .number).keyboardType(.decimalPad)
                    TextField("Tempo totale in secondi", value: $draft.bestPerformances[index].durationS, format: .number).keyboardType(.decimalPad)
                    TextField("Contesto e data (facoltativi)", text: $draft.bestPerformances[index].note)
                    Button("Rimuovi prestazione", role: .destructive) { draft.bestPerformances.remove(at: index) }
                }
                Button("Aggiungi una prestazione") { draft.bestPerformances.append(BestPerformance()) }.disabled(draft.bestPerformances.count >= 20)
                Text("Inserisci i tuoi valori: sono prestazioni dichiarate, non test fisiologici verificati.").font(.footnote).foregroundStyle(.secondary)
            }
        }
    }
    private var availabilitySection: some View {
        Group {
            Section("Giorni e tempo totale disponibile") {
                ForEach(0..<7, id: \.self) { day in
                    Toggle(weekdays[day], isOn: Binding(get: { draft.availability.contains { $0.weekday == day } }, set: { enabled in
                        draft.availability.removeAll { $0.weekday == day }
                        if enabled { draft.availability.append(TrainingDay(weekday: day, minutes: 45)) }
                    }))
                    if let index = draft.availability.firstIndex(where: { $0.weekday == day }) {
                        Stepper("Fino a \(draft.availability[index].minutes) minuti", value: $draft.availability[index].minutes, in: 15...240, step: 5)
                    }
                }
                Text("Il tempo include corsa, bici e palestra; il coach deve rispettarlo.").font(.footnote).foregroundStyle(.secondary)
            }
            Section("Palestra e vincoli") {
                Stepper("Palestra/forza: \(draft.gymSessionsWeek) sedute/settimana", value: $draft.gymSessionsWeek, in: 0...7)
                TextField("Come ti alleni in palestra?", text: $draft.gymNotes, axis: .vertical)
                TextField("Impegni, limitazioni o dolore che vuoi segnalare (facoltativo)", text: $draft.constraints, axis: .vertical).lineLimit(3...6)
                Text("Condividi solo ciò che vuoi far considerare al coach. Il servizio non fa diagnosi.").font(.footnote).foregroundStyle(.secondary)
            }
        }
    }
    private var summarySection: some View {
        Section("Controlla prima di partire") {
            Text(draft.goalDescription).font(.headline)
            Text(hasDeadline ? "Obiettivo entro \(calendarString(deadline))" : "Scadenza da definire con il coach")
            Text("Dispositivo: \(draft.deviceVendor == "none" ? "nessuno" : draft.deviceVendor)")
            ForEach(draft.availability.sorted { $0.weekday < $1.weekday }) { day in Text("\(weekdays[day.weekday]): \(day.minutes) min") }
            Text("Palestra: \(draft.gymSessionsWeek) sedute/sett. · \(draft.bestPerformances.count) migliori prestazioni dichiarate")
            Toggle("Confermo l'uso delle risposte per il coaching", isOn: $draft.coachingConsent)
            Text("Il profilo viene inviato al servizio di coaching configurato. Non cambia il piano e non concede permessi HealthKit. L'invio a un assistente AI richiede un flusso e un consenso separati.").font(.footnote).foregroundStyle(.secondary)
        }
    }
    private func calendarString(_ value: Date) -> String {
        let formatter = DateFormatter(); formatter.calendar = Calendar(identifier: .gregorian)
        formatter.locale = Locale(identifier: "en_US_POSIX"); formatter.dateFormat = "yyyy-MM-dd"
        return formatter.string(from: value)
    }
    private func loadDraft() {
        guard !initialized else { return }; initialized = true
        if let profile = store.profile?.profile {
            draft = profile; hasDeadline = profile.targetDate != nil
            if let date = profile.targetDate { let formatter = DateFormatter(); formatter.dateFormat = "yyyy-MM-dd"; deadline = formatter.date(from: date) ?? deadline }
            weight = profile.weightKg.map { String($0) } ?? ""; height = profile.heightCm.map { String($0) } ?? ""; age = profile.ageYears.map { String($0) } ?? ""
        }
    }
    private func optionalNumber(_ value: String, min: Double, max: Double) throws -> Double? {
        let text = value.trimmingCharacters(in: .whitespacesAndNewlines)
        if text.isEmpty { return nil }
        guard let number = Double(text.replacingOccurrences(of: ",", with: ".")), number.isFinite, number >= min, number <= max else {
            throw ServiceError(status: 0, code: "profile_value", message: "Controlla età, peso e altezza: puoi lasciarli vuoti oppure inserire un valore valido.")
        }; return number
    }
    private func validateAndAdvance() {
        do {
            if step == 0 && draft.goalDescription.trimmingCharacters(in: .whitespacesAndNewlines).count < 10 { throw ServiceError(status: 0, code: "profile_goal", message: "Descrivi l'obiettivo con almeno 10 caratteri.") }
            if step == 1 {
                draft.weightKg = try optionalNumber(weight, min: 30, max: 350); draft.heightCm = try optionalNumber(height, min: 120, max: 240)
                let years = try optionalNumber(age, min: 18, max: 110)
                if let years, years.rounded() != years { throw ServiceError(status: 0, code: "profile_age", message: "Inserisci l'età in anni interi.") }
                draft.ageYears = years.map { Int($0) }
            }
            if step == 3 && draft.availability.isEmpty { throw ServiceError(status: 0, code: "profile_days", message: "Scegli almeno un giorno disponibile.") }
            step += 1
        } catch { store.errorMessage = error.localizedDescription }
    }
    private func save() {
        draft.targetDate = hasDeadline ? calendarString(deadline) : nil
        if !hasDeadline { draft.deadlineFlexible = true }
        if draft.deviceVendor == "none" { draft.deviceModel = "" }
        Task { await store.run { try await store.saveProfile(draft); if editing { dismiss() } } }
    }
}

struct CoachHomeView: View {
    @EnvironmentObject private var store: CoachStore
    @State private var editing = false
    @State private var recording = false
    private let weekdays = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]
    var body: some View {
        NavigationStack {
            List {
                if let profile = store.profile?.profile {
                    Section("Il tuo obiettivo") {
                        Text(profile.goalDescription).font(.headline)
                        Text(profile.targetDate.map { "Entro \($0)" } ?? "Scadenza da definire con il coach")
                        Button("Aggiorna obiettivi e profilo") { editing = true }
                    }
                    Section("Spazio per allenarti") {
                        ForEach(profile.availability.sorted { $0.weekday < $1.weekday }) { day in LabeledContent(weekdays[day.weekday], value: "\(day.minutes) min") }
                        Text("Palestra/forza: \(profile.gymSessionsWeek) sedute/settimana, da includere nel tempo disponibile.").font(.footnote)
                    }
                    Section("Feedback e assistente") {
                        Button("Registra una seduta senza orologio") { recording = true }.disabled(store.busy)
                        Text(profile.deviceVendor == "none" ? "Il coach può usare obiettivi, durata e sensazioni anche senza orologio. Le metriche non misurate resteranno assenti." : "Il dispositivo selezionato è \(profile.deviceVendor). Scelta del produttore e collegamento dell'account sono passaggi distinti.")
                        Text("Puoi parlare con ChatGPT nella versione personale locale. Il collegamento AI remoto per questa app iOS è ancora da abilitare.").font(.footnote).foregroundStyle(.secondary)
                        Text(store.plan == nil ? "Il profilo è pronto. La creazione AI del programma è disponibile nel coach locale; qui puoi importare un piano dalla scheda Piano." : "Apri Review per valutare la seduta e Consigli per la prossima scelta.")
                    }
                    if !store.manualSessions.isEmpty {
                        Section("Feedback recenti") {
                            ForEach(store.manualSessions, id: \.activityId) { session in
                                VStack(alignment: .leading, spacing: 6) {
                                    Text(session.name).font(.headline)
                                    Text("\(session.date) · \(Metric.duration(session.durationS)) dichiarati")
                                    if let feedback = session.feedback {
                                        Text("Sforzo: \(feedback.perceivedExertion.map(String.init) ?? "—")/10 · \(FeedbackText.feeling(feedback.feeling))").font(.footnote)
                                        if !feedback.notes.isEmpty { Text(feedback.notes).font(.footnote).foregroundStyle(.secondary) }
                                    }
                                }
                            }
                        }
                    }
                }
            }.navigationTitle("Il tuo coach")
                .sheet(isPresented: $editing) { OnboardingView(editing: true).environmentObject(store) }
                .sheet(isPresented: $recording) { ManualSessionView().environmentObject(store) }
                .refreshable { await store.run { try await store.refresh() } }
        }
    }
}
