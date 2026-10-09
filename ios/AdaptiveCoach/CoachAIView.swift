import SwiftUI

struct CoachAIView: View {
    @EnvironmentObject private var store: CoachStore
    @ObservedObject var connection: ChatGPTConnection
    @State private var models: [ChatGPTModel] = []
    @State private var model = ""
    @State private var question = "Valuta la mia ultima seduta considerando obiettivo, piano e storico. Dimmi cosa è riuscito e cosa correggere nella prossima."
    @State private var answer = ""
    @State private var consent = false
    @State private var working = false
    @State private var error: String?
    private let http = ChatGPTHTTP()

    var body: some View {
        Section("Il cervello del tuo coach · ChatGPT") {
            if let credential = connection.credential {
                Text(credential.identity.email ?? "Account ChatGPT collegato").font(.headline)
                Text(credential.permitsInference ? "Using ChatGPT plan" : "Permesso di usare il piano non attivo")
                    .font(.footnote).foregroundStyle(.secondary)
            }
            Text("Collegamento sperimentale: il login reale su iPhone deve ancora essere verificato.").font(.footnote).foregroundStyle(.secondary)
            Text("Collega il tuo account ChatGPT per la review AI. Non serve una chiave API. L'idoneità del piano e la disponibilità del collegamento sono stabilite da OpenAI.").font(.footnote)
            Button(connection.credential?.permitsInference == false ? "Continue with ChatGPT · abilita il piano" : "Continue with ChatGPT") {
                Task { await connection.connect() }
            }.accessibilityIdentifier("chatgpt-connect").disabled(connection.connecting || working || store.busy)
            if connection.connecting { ProgressView("Collegamento in corso…") }
            if let message = connection.message { Text(message).font(.footnote).foregroundStyle(.secondary) }
            Link("Gestisci utilizzo ChatGPT", destination: URL(string: "https://chatgpt.com/settings/usage")!)
            if connection.credential != nil {
                Button("Scollega ChatGPT", role: .destructive) {
                    Task { do { try await connection.disconnect(); models = []; model = ""; answer = "" }
                        catch { self.error = error.localizedDescription } }
                }.disabled(working || connection.connecting)
            }
            if connection.credential?.permitsInference == true && !connection.needsWelcome {
                Button("Carica i modelli disponibili") { Task { await loadModels() } }.disabled(working || store.busy)
                if !models.isEmpty {
                    Picker("Modello", selection: $model) { ForEach(models) { item in Text(item.name).tag(item.id) } }.disabled(working)
                    TextField("Che cosa vuoi chiedere al coach?", text: $question, axis: .vertical).lineLimit(3...8).disabled(working)
                    Toggle("Acconsento all'invio a OpenAI di profilo, programma, storico e metriche della seduta per questa risposta", isOn: $consent).disabled(working)
                    Text("Il contesto esclude il percorso GPS e le credenziali. Le risposte testuali del profilo sono incluse. La risposta usa i limiti del tuo piano ChatGPT.").font(.footnote).foregroundStyle(.secondary)
                    Button("Chiedi una review al coach") { Task { await ask() } }
                        .disabled(working || store.busy || !consent || question.count < 5 || question.count > 2000 || model.isEmpty)
                }
            }
            if working { ProgressView("Preparazione o analisi…") }
            if let error { Text(error).foregroundStyle(.orange) }
            if !answer.isEmpty { Text(answer).textSelection(.enabled) }
        }
        .alert("You're using your ChatGPT plan", isPresented: $connection.needsWelcome) {
            Button("Got it") { do { try connection.acknowledgeWelcome() } catch { self.error = error.localizedDescription } }
        } message: {
            Text("Le richieste AI idonee useranno i limiti del tuo piano ChatGPT o i crediti disponibili. Puoi gestire accesso e utilizzo nelle impostazioni ChatGPT. Non riceviamo le tue conversazioni o memoria.")
        }
        .onChange(of: connection.accountGeneration) { _, _ in models = []; model = ""; answer = ""; consent = false }
    }
    private func loadModels() async {
        guard !working else { return }; working = true; error = nil
        defer { working = false }
        let generation = connection.accountGeneration
        do {
            let token = try await connection.accessToken()
            let values = try await http.models(token: token)
            guard generation == connection.accountGeneration else { throw ChatGPTAuthorization.failure() }
            models = values; model = values.first?.id ?? ""
            if values.isEmpty { error = "Nessun modello disponibile per questo account." }
        } catch { self.error = error.localizedDescription }
    }
    private func ask() async {
        guard !working, consent, models.contains(where: { $0.id == model }), let athleteID = store.identity?.id else { return }
        working = true; error = nil; answer = ""
        defer { working = false; consent = false }
        let generation = connection.accountGeneration
        let selectedModel = model, submittedQuestion = question
        do {
            let evidence = try await store.coachingContext()
            guard generation == connection.accountGeneration, store.identity?.id == athleteID else { throw ChatGPTAuthorization.failure() }
            let token = try await connection.accessToken()
            let current = try await http.models(token: token)
            guard generation == connection.accountGeneration, store.identity?.id == athleteID,
                  current.contains(where: { $0.id == selectedModel }) else { throw ChatGPTAuthorization.failure() }
            let response = try await http.review(context: evidence.context, question: submittedQuestion, model: selectedModel, token: token)
            let latest = try await store.coachingContext()
            guard generation == connection.accountGeneration, store.identity?.id == athleteID,
                  latest.contextHash == evidence.contextHash else {
                throw ServiceError(status: 409, code: "chatgpt_context_changed", message: "Profilo o evidenze sono cambiati durante la risposta. Aggiorna e ripeti la review.")
            }
            answer = response
        } catch { self.error = error.localizedDescription }
    }
}
