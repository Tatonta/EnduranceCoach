import SwiftUI
import UIKit

struct SettingsView: View {
    @EnvironmentObject private var store: CoachStore
    @State private var deleting = false
    @State private var deletionPassword = ""
    @State private var deletionConfirmed = false
    @State private var editingProfile = false
    private var healthPresented: Binding<Bool> {
        Binding(get: { !store.healthPreview.isEmpty }, set: { if !$0 { store.discardHealthPreview() } })
    }
    private var sharing: Binding<Bool> {
        Binding(get: { store.exportURL != nil }, set: { if !$0 { store.removeExport() } })
    }
    var body: some View {
        NavigationStack {
            List {
                Section("Account") {
                    Text(store.identity?.email ?? "")
                    Text(store.endpointText).font(.footnote).foregroundStyle(.secondary)
                    Button("Esci") { Task { await store.run { try await store.logout() } } }.disabled(store.busy)
                }
                Section("Il tuo coach") {
                    Button("Modifica profilo e obiettivi") { editingProfile = true }.disabled(store.busy)
                    Text("Obiettivo, scadenza, disponibilità, esperienza e palestra guidano il coaching.").font(.footnote).foregroundStyle(.secondary)
                }
                Section("Importazione Apple Health") {
                    Text("Leggi i workout degli ultimi 42 giorni. Puoi controllare l'anteprima prima di inviarli al servizio.")
                    Text("La disponibilità dipende dai dati che l'app dell'orologio scrive in Apple Health e dai tuoi permessi. Non è un collegamento diretto alle API del produttore.").font(.footnote).foregroundStyle(.secondary)
                    Button("Leggi e prepara anteprima") { Task { await store.run { try await store.previewHealth() } } }.disabled(store.busy)
                }
                Section("Connessioni ai produttori") {
                    ForEach(store.vendors.filter { $0.id != "apple_health" }) { vendor in
                        VStack(alignment: .leading, spacing: 5) {
                            Text(vendor.name).font(.headline)
                            Text("In preparazione · nessuna connessione attiva").font(.footnote).foregroundStyle(.secondary)
                            Text(vendor.notes).font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }
                Section("I tuoi dati") {
                    Button("Esporta i dati dell'account") { Task { await store.run { try await store.exportAccount() } } }.disabled(store.busy)
                    Button("Elimina account", role: .destructive) { deletionPassword = ""; deletionConfirmed = false; deleting = true }.disabled(store.busy)
                    Text("L'esportazione contiene dati di allenamento. Scegli tu dove condividerla o salvarla.").font(.footnote).foregroundStyle(.secondary)
                }
                if store.busy { ProgressView("Operazione in corso…") }
            }.navigationTitle("Account")
                .sheet(isPresented: $editingProfile) { OnboardingView(editing: true).environmentObject(store) }
                .sheet(isPresented: healthPresented) { HealthPreviewView().environmentObject(store) }
                .sheet(isPresented: sharing, onDismiss: { store.removeExport() }) {
                    if let url = store.exportURL { ExportShareView(url: url) { store.removeExport() } }
                }
                .sheet(isPresented: $deleting, onDismiss: { deletionPassword = "" }) {
                    NavigationStack {
                        Form {
                            Text("Elimina definitivamente l'account, i piani e le attività dal servizio. Questa azione non elimina gli originali dall'orologio o da Apple Health.")
                            SecureField("Conferma la password", text: $deletionPassword).textContentType(.password)
                            Toggle("Confermo l'eliminazione definitiva", isOn: $deletionConfirmed)
                            Button("Elimina definitivamente", role: .destructive) {
                                Task {
                                    await store.run { try await store.deleteAccount(password: deletionPassword); deleting = false }
                                    deletionPassword = ""
                                }
                            }.disabled(store.busy || !deletionConfirmed || deletionPassword.count < 12)
                        }.navigationTitle("Elimina account")
                            .toolbar { Button("Annulla") { deleting = false }.disabled(store.busy) }
                            .interactiveDismissDisabled(store.busy)
                    }
                }
        }
    }
}

struct HealthPreviewView: View {
    @EnvironmentObject private var store: CoachStore
    @Environment(\.dismiss) private var dismiss
    @State private var consent = false
    @State private var readRoute = false
    var body: some View {
        NavigationStack {
            List {
                Section("Prima dell'invio") {
                    Text("\(store.healthPreview.count) workout, con date, sport, durata, distanza e — se leggibili — FC e dislivello.")
                    Text("Destinazione: \(store.endpointText)\nAccount: \(store.identity?.email ?? "")").font(.footnote)
                    Text("Se una corsa era davvero facile, puoi indicarlo nel nome. Il passo da solo non ne determina l'intensità. I dati mancanti restano mancanti.")
                    Text("L'anteprima contiene solo dati leggibili: permessi limitati o dati che l'app dell'orologio non esporta possono rendere incompleta la cronologia.").font(.footnote).foregroundStyle(.secondary)
                    Toggle("Leggi anche il percorso GPS per i dettagli selezionati", isOn: $readRoute)
                    Text("La lettura del percorso e il suo invio al servizio sono scelte separate. Non leggiamo la posizione attuale.").font(.footnote).foregroundStyle(.secondary)
                }
                Section("Workout da importare") {
                    ForEach(store.healthPreview.indices, id: \.self) { index in
                        VStack(alignment: .leading, spacing: 5) {
                            TextField("Nome della seduta", text: $store.healthPreview[index].name).disabled(store.busy)
                            let item = store.healthPreview[index]
                            Text("\(item.startTime) · \(item.sport)").font(.caption)
                            Text(String(format: "%.2f km · %@", item.distanceM / 1000, Metric.duration(item.durationS))).font(.footnote)
                            Text("FC: \(item.avgHr.map { String(format: "%.0f bpm", $0) } ?? "non disponibile") · D+: \(item.elevationGainM.map { String(format: "%.0f m", $0) } ?? "non disponibile")").font(.footnote).foregroundStyle(.secondary)
                            if ["running", "cycling"].contains(item.sport) {
                                Button(store.healthDetails[item.sourceActivityId] == nil ? "Leggi lap, campioni e dinamiche" : "Rileggi i dettagli selezionati") {
                                    Task { await store.run { try await store.previewHealthDetails(item, includeRoute: readRoute) } }
                                }.disabled(store.busy)
                            }
                            if let details = store.healthDetails[item.sourceActivityId] {
                                Text("Includi: \(details.laps.count) lap, \(details.samples.count) campioni, \(details.routeSegments.reduce(0) { $0 + $1.count }) punti GPS").font(.caption)
                            }
                        }
                    }
                }
                Section {
                    Toggle("Acconsento all'invio di questi dati di allenamento al mio account sul servizio indicato", isOn: $consent)
                    Button("Importa nel mio account") { Task { await store.run { try await store.uploadHealth() } } }
                        .disabled(store.busy || !consent || store.healthPreview.contains { $0.name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty })
                }
            }.navigationTitle("Anteprima Apple Health").navigationBarTitleDisplayMode(.inline)
                .toolbar { Button("Annulla") { dismiss() }.disabled(store.busy) }
                .interactiveDismissDisabled(store.busy)
                .sheet(item: $store.healthDetailCandidate) { candidate in HealthDetailPreviewView(candidate: candidate).environmentObject(store) }
        }
    }
}

struct HealthDetailPreviewView: View {
    @EnvironmentObject private var store: CoachStore
    @Environment(\.dismiss) private var dismiss
    @State private var consent = false
    @State private var sendRoute = false
    let candidate: HealthDetailCandidate
    var body: some View {
        NavigationStack {
            List {
                Section("Dettagli letti da Apple Health") {
                    Text(candidate.activity.name).font(.headline)
                    LabeledContent("Lap registrati", value: String(candidate.evidence.laps.count))
                    LabeledContent("Campioni da inviare", value: String(candidate.evidence.samples.count))
                    LabeledContent("Timestamp originali", value: String(candidate.evidence.reportedSampleCount))
                    LabeledContent("Stride length", value: candidate.evidence.dynamics.strideM.map { String(format: "%.2f m", $0) } ?? "Non disponibile")
                    LabeledContent("Contatto a terra", value: candidate.evidence.dynamics.groundContactS.map { String(format: "%.1f ms", $0 * 1000) } ?? "Non disponibile")
                    Text(candidate.evidence.coverageNote).font(.footnote).foregroundStyle(.secondary)
                    Text("Lettura limitata al workout scelto. Fasi e target non vengono dedotti dal nome o dalla posizione dei lap.").font(.footnote)
                }
                Section("Percorso GPS") {
                    Text("\(candidate.rawRouteCount) punti letti; \(candidate.evidence.routeSegments.reduce(0) { $0 + $1.count }) punti selezionati in segmenti distinti.")
                    if !candidate.evidence.routeSegments.isEmpty { Toggle("Includi anche il percorso GPS nell'invio al servizio", isOn: $sendRoute) }
                    Text("Il percorso è facoltativo. Puoi usare campioni e dinamiche senza condividerlo.").font(.footnote).foregroundStyle(.secondary)
                }
                Section {
                    Text("Destinazione: \(store.endpointText)").font(.footnote)
                    Toggle("Includi questi dettagli nella prossima importazione", isOn: $consent)
                    Button("Aggiungi all'anteprima da inviare") { store.includeHealthDetails(candidate, sendRoute: sendRoute); dismiss() }
                        .disabled(!consent || (!sendRoute && candidate.evidence.laps.isEmpty && candidate.evidence.samples.isEmpty))
                    if candidate.evidence.laps.isEmpty && candidate.evidence.samples.isEmpty { Text("È disponibile solo il percorso: puoi includerlo esplicitamente oppure annullare e importare il riepilogo.").font(.footnote) }
                    Text("Questa scelta prepara l'anteprima. I dati saranno inviati solo premendo Importa nel mio account nella schermata precedente.").font(.footnote).foregroundStyle(.secondary)
                }
            }.navigationTitle("Anteprima dei dettagli")
                .toolbar { Button("Annulla") { store.healthDetailCandidate = nil; dismiss() } }
        }
    }
}

struct ExportShareView: UIViewControllerRepresentable {
    let url: URL
    let onComplete: () -> Void
    func makeUIViewController(context: Context) -> UIActivityViewController {
        let controller = UIActivityViewController(activityItems: [url], applicationActivities: nil)
        controller.completionWithItemsHandler = { _, _, _, _ in
            DispatchQueue.main.async { onComplete() }
        }
        return controller
    }
    func updateUIViewController(_ controller: UIActivityViewController, context: Context) {}
}
