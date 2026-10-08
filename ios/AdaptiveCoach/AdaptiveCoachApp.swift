import SwiftUI

@main
struct AdaptiveCoachApp: App {
    @StateObject private var store = CoachStore()
    @Environment(\.scenePhase) private var scenePhase
    var body: some Scene {
        WindowGroup {
            RootView().environmentObject(store)
                .overlay {
                    if scenePhase != .active {
                        Color(.systemBackground).ignoresSafeArea()
                            .overlay(Label("Adaptive Coach", systemImage: "figure.run").font(.title))
                    }
                }
                .task { await store.restore() }
                .onChange(of: scenePhase) { _, phase in
                    if phase != .active { store.invalidateReview() }
                    else if store.signedIn { Task { await store.run { try await store.refresh() } } }
                }
        }
    }
}

struct RootView: View {
    @EnvironmentObject private var store: CoachStore
    private var messagePresented: Binding<Bool> {
        Binding(get: { store.errorMessage != nil || store.notice != nil },
                set: { if !$0 { store.errorMessage = nil; store.notice = nil } })
    }
    var body: some View {
        Group {
            if store.signedIn {
                TabView {
                    ReviewView().tabItem { Label("Review", systemImage: "chart.bar.doc.horizontal") }
                    AdviceView().tabItem { Label("Consigli", systemImage: "lightbulb") }
                    PlanView().tabItem { Label("Piano", systemImage: "calendar") }
                    SettingsView().tabItem { Label("Account", systemImage: "person.crop.circle") }
                }
            } else { LoginView() }
        }
        .tint(.indigo)
        .alert(store.errorMessage != nil ? "Operazione non completata" : "Adaptive Coach", isPresented: messagePresented) {
            Button("OK", role: .cancel) { store.errorMessage = nil; store.notice = nil }
        } message: { Text(store.errorMessage ?? store.notice ?? "") }
        .sheet(item: $store.proposal) { AdjustmentSheet(proposal: $0).environmentObject(store) }
    }
}

struct LoginView: View {
    @EnvironmentObject private var store: CoachStore
    @State private var email = ""
    @State private var password = ""
    @State private var register = false
    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Label("Adaptive Coach", systemImage: "figure.run").font(.title2.bold())
                    Text("Review dell'ultima seduta e consigli per continuare il tuo piano.")
                }
                Section("Servizio di coaching") {
                    TextField("https://coach.example.com", text: $store.endpointText)
                        .textInputAutocapitalization(.never).autocorrectionDisabled().keyboardType(.URL)
                        .accessibilityIdentifier("service-origin")
                    Text("Usa l'indirizzo fornito dal gestore del servizio. Credenziali e workout vengono inviati a questo indirizzo.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
                Section(register ? "Crea account" : "Accedi") {
                    TextField("Email", text: $email).textContentType(.username).keyboardType(.emailAddress)
                        .textInputAutocapitalization(.never).autocorrectionDisabled()
                    SecureField("Password (almeno 12 caratteri)", text: $password)
                        .textContentType(register ? .newPassword : .password)
                    Toggle("Crea un nuovo account", isOn: $register)
                    if register { Text("La registrazione deve essere abilitata dal gestore del servizio.").font(.footnote) }
                    Button(register ? "Crea account e accedi" : "Accedi") {
                        Task {
                            await store.run { try await store.signIn(email: email, password: password, register: register) }
                            password = ""
                        }
                    }.disabled(store.busy || email.isEmpty || password.count < 12 || store.endpointText.isEmpty)
                }
                if store.busy { ProgressView("Connessione…") }
            }.navigationTitle("Il tuo coach")
        }
    }
}
