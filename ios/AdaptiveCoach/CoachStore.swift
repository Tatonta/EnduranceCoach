import Foundation
import SwiftUI

@MainActor
final class CoachStore: ObservableObject {
    @Published var endpointText = UserDefaults.standard.string(forKey: "serviceOrigin") ?? ""
    @Published private(set) var identity: Identity?
    @Published private(set) var review: WorkoutReview?
    @Published private(set) var plan: PlanReply?
    @Published private(set) var profile: ProfileReply?
    @Published private(set) var profileChecked = false
    @Published private(set) var manualSessions: [ActivityMetrics] = []
    @Published private(set) var vendors: [Vendor] = []
    @Published private(set) var busy = false
    @Published var errorMessage: String?
    @Published var notice: String?
    @Published var proposal: AdjustmentProposal?
    @Published var healthPreview: [ImportedActivity] = []
    @Published var healthDetailCandidate: HealthDetailCandidate?
    @Published private(set) var healthDetails: [String: HealthEvidence] = [:]
    @Published var pendingPlan: JSONValue?
    @Published var exportURL: URL?
    private var client: APIClient?
    private var reviewedAt: Date?
    private var bootstrapped = false
    private let health = HealthImporter()
    let chatgpt = ChatGPTConnection()
    init() {
        // Clean a protected export left behind if the previous process ended during sharing.
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("CoachExports", isDirectory: true)
        try? FileManager.default.removeItem(at: directory)
    }
    var signedIn: Bool { identity != nil }
    var canOfferAdjustment: Bool {
        guard !busy, let reviewedAt, Date().timeIntervalSince(reviewedAt) < 60 else { return false }
        return review?.program.eligible == true
    }
    var reviewIsCurrent: Bool { reviewedAt != nil }

    // All health data stays in memory. No offline adjustment or local health-response cache.
    func invalidateReview() { reviewedAt = nil; proposal = nil }
    func run(_ operation: @MainActor () async throws -> Void) async {
        guard !busy else { return }
        busy = true
        errorMessage = nil
        defer { busy = false }
        do { try await operation() }
        catch {
            invalidateReview()
            if let failure = error as? ServiceError, failure.status == 401 {
                do { try SessionVault.clear() } catch { errorMessage = error.localizedDescription }
                clearMemory()
                errorMessage = errorMessage ?? "Sessione scaduta. Accedi di nuovo."
            } else { errorMessage = error.localizedDescription }
        }
    }
    func restore() async {
        guard !bootstrapped else { return }
        bootstrapped = true
        await run {
            guard let secret = try SessionVault.read() else { return }
            let endpoint = try Endpoint.validate(secret.endpoint)
            let api = APIClient(endpoint: endpoint, token: secret.token)
            let me: Identity = try await api.request("v1/me")
            guard me.id == secret.athleteID else {
                try SessionVault.clear()
                throw ServiceError(status: 401, code: "session_owner", message: "La sessione appartiene a un altro account.")
            }
            self.endpointText = secret.endpoint
            self.client = api
            self.identity = me
            try self.chatgpt.load(endpoint: secret.endpoint, athleteID: me.id)
            try await self.refresh()
        }
    }
    func signIn(email: String, password: String, register: Bool) async throws {
        let endpoint = try Endpoint.validate(endpointText)
        let api = APIClient(endpoint: endpoint)
        if register {
            let _: Identity = try await api.request("v1/auth/register", method: "POST", body: Wire.encoder().encode(
                Registration(email: email, password: password, timezone: TimeZone.current.identifier)))
        }
        let login: LoginReply = try await api.request("v1/auth/login", method: "POST", body: Wire.encoder().encode(Credentials(email: email, password: password)))
        api.token = login.accessToken
        let me: Identity = try await api.request("v1/me")
        try SessionVault.write(SessionSecret(endpoint: endpoint.absoluteString, token: login.accessToken, athleteID: me.id))
        UserDefaults.standard.set(endpoint.absoluteString, forKey: "serviceOrigin")
        client = api
        identity = me
        try chatgpt.load(endpoint: endpoint.absoluteString, athleteID: me.id)
        try await refresh()
    }
    private func api() throws -> APIClient {
        guard let client, identity != nil else { throw ServiceError(status: 401, code: "session", message: "Accedi al tuo account.") }
        return client
    }
    func refresh() async throws {
        invalidateReview()
        let api = try api()
        do { profile = try await api.request("v1/profile"); profileChecked = true }
        catch let error as ServiceError where error.code == "profile_required" {
            profile = nil; profileChecked = true
        }
        guard profile != nil else { plan = nil; review = nil; return }
        let activityList: ActivityList = try await api.request("v1/activities", query: [URLQueryItem(name: "limit", value: "50")])
        manualSessions = Array(activityList.activities.filter { $0.source == "manual" }.prefix(5))
        do { plan = try await api.request("v1/plan") }
        catch let error as ServiceError where error.code == "plan_required" {
            plan = nil; review = nil
        }
        if plan != nil {
            let latest: WorkoutReview = try await api.request("v1/review/workout")
            review = latest
            reviewedAt = Date()
        }
        let integrations: IntegrationsReply = try await api.request("v1/integrations")
        vendors = integrations.vendors
    }
    func saveProfile(_ value: TrainingProfile) async throws {
        let result: ProfileReply = try await api().request("v1/profile", method: "PUT",
            body: Wire.encoder().encode(ProfileWrite(expectedVersion: profile?.version ?? 0, profile: value)))
        profile = result
        profileChecked = true
        try await refresh()
    }
    func coachingContext() async throws -> CoachingContextReply {
        try await api().request("v1/coach/context")
    }
    func previewInitialPlan(_ request: InitialPlanRequest) async throws -> InitialPlanPreview {
        try await api().request("v1/coach/initial-plan/preview", method: "POST", body: Wire.encoder().encode(request))
    }
    func applyInitialPlan(_ preview: InitialPlanPreview) async throws {
        let body = InitialPlanAcceptance(expectedContextHash: preview.contextHash, plan: preview.plan,
                                         explanation: preview.explanation, draftHash: preview.draftHash,
                                         expiresAt: preview.expiresAt, confirmed: true)
        let _: PlanReply = try await api().request("v1/coach/initial-plan/apply", method: "POST", body: Wire.encoder().encode(body))
        try await refresh()
        notice = "Programma iniziale salvato. Le sedute sono disponibili nella scheda Piano."
    }
    func saveManualSession(_ value: ManualSessionRequest) async throws {
        let _: ImportReply = try await api().request("v1/activities/manual", method: "POST", body: Wire.encoder().encode(value))
        try await refresh()
        notice = "Feedback salvato nel tuo storico. Durata e sensazioni sono dati dichiarati."
    }
    func previewAdjustment() async throws {
        // Always retrieve fresh evidence before creating a server-owned proposal.
        try await refresh()
        guard review?.program.eligible == true else { return }
        proposal = try await api().request("v1/review/adjustments/preview", method: "POST")
    }
    func applyAdjustment(_ proposal: AdjustmentProposal) async throws {
        guard let expiration = Wire.date(proposal.expiresAt), expiration > Date() else {
            throw ServiceError(status: 409, code: "proposal_stale", message: "Anteprima scaduta. Aggiorna la review e crea una nuova anteprima.")
        }
        // The server additionally checks owner, evidence hash, current date and version atomically.
        let result: ApplyReply = try await api().request("v1/review/adjustments/\(proposal.proposalId)/apply", method: "POST",
            body: Wire.encoder().encode(Acceptance(expectedVersion: proposal.baseVersion, confirmed: true)))
        self.proposal = nil
        invalidateReview()
        notice = "Piano aggiornato alla versione \(result.version). L'invio all'orologio non è ancora disponibile."
        try await refresh()
    }
    func previewHealth() async throws {
        healthPreview = []
        healthDetailCandidate = nil; healthDetails = [:]
        healthPreview = try await health.preview()
        if healthPreview.isEmpty {
            notice = "Nessun workout leggibile negli ultimi 42 giorni. Potrebbero non esserci dati oppure l'accesso di lettura potrebbe essere limitato. Puoi controllare i permessi in Apple Health."
        }
    }
    func uploadHealth() async throws {
        guard !healthPreview.isEmpty else { return }
        let result: ImportReply = try await api().request("v1/activities/import", method: "POST", body: Wire.encoder().encode(ActivityImport(activities: healthPreview)))
        let api = try api()
        for activity in healthPreview {
            guard let evidence = healthDetails[activity.sourceActivityId] else { continue }
            guard let originalHash = result.sourceActivityHashes?.first(where: { $0.source == "apple_health" && $0.sourceActivityId == activity.sourceActivityId })?.activityHash else {
                throw ServiceError(status: 409, code: "health_backend_contract", message: "Riepiloghi salvati; il backend deve supportare gli hash di importazione per inviare i dettagli in modo coerente.")
            }
            let path = "v1/activities/apple_health/\(activity.sourceActivityId)/details"
            let state: DetailStateReply = try await api.request(path)
            guard state.activityHash == originalHash else {
                throw ServiceError(status: 409, code: "health_source_changed", message: "Riepilogo cambiato durante l'importazione. I dettagli non sono stati associati; ripeti l'anteprima.")
            }
            let _: JSONValue = try await api.request(path, method: "PUT", body: Wire.encoder().encode(
                HealthDetailWrite(expectedDetailsVersion: state.version, expectedActivityHash: originalHash, details: evidence)))
        }
        healthPreview = []
        healthDetailCandidate = nil; healthDetails = [:]
        notice = "\(result.imported) record importati; \(result.uniqueWorkouts) workout distinti nell'account."
        try await refresh()
    }
    func previewHealthDetails(_ activity: ImportedActivity, includeRoute: Bool) async throws {
        guard healthDetails.count < 10 || healthDetails[activity.sourceActivityId] != nil else {
            throw ServiceError(status: 0, code: "health_detail_selection", message: "Seleziona al massimo 10 sedute dettagliate per importazione. Puoi importare poi le altre.")
        }
        healthDetailCandidate = nil
        healthDetailCandidate = try await health.previewDetails(activity, includeRoute: includeRoute)
    }
    func includeHealthDetails(_ candidate: HealthDetailCandidate, sendRoute: Bool) {
        guard let index = healthPreview.firstIndex(where: { $0.sourceActivityId == candidate.activity.sourceActivityId }) else { return }
        var source = candidate.activity; source.name = healthPreview[index].name
        healthPreview[index] = source
        var evidence = candidate.evidence
        if !sendRoute { evidence.routeSegments = [] }
        guard evidence.hasEvidence else { return }
        healthDetails[source.sourceActivityId] = evidence
        healthDetailCandidate = nil
    }
    func discardHealthPreview() {
        healthPreview = []; healthDetailCandidate = nil; healthDetails = [:]
    }
    func readPlanFile(_ url: URL) throws {
        let scoped = url.startAccessingSecurityScopedResource()
        defer { if scoped { url.stopAccessingSecurityScopedResource() } }
        let values = try url.resourceValues(forKeys: [.fileSizeKey])
        guard let size = values.fileSize, size <= 1_900_000 else {
            throw ServiceError(status: 0, code: "file_size", message: "Il piano JSON deve essere inferiore a 1,9 MB.")
        }
        let data = try Data(contentsOf: url)
        guard data.count <= 1_900_000 else { throw URLError(.dataLengthExceedsMaximum) }
        _ = try Wire.decoder().decode(TrainingPlan.self, from: data)
        pendingPlan = try JSONDecoder().decode(JSONValue.self, from: data)
    }
    func savePendingPlan() async throws {
        guard let pendingPlan else { return }
        let _: PlanReply = try await api().request("v1/plan", method: "PUT", body: Wire.encoder().encode(PlanWrite(expectedVersion: plan?.version ?? 0, plan: pendingPlan)))
        self.pendingPlan = nil
        try await refresh()
    }
    func exportAccount() async throws {
        removeExport()
        let data = try await api().raw("v1/me/export")
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("CoachExports", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true,
                                                attributes: [.protectionKey: FileProtectionType.complete])
        var url = directory.appendingPathComponent("account-\(UUID().uuidString).json")
        try data.write(to: url, options: [.atomic, .completeFileProtection])
        var resources = URLResourceValues(); resources.isExcludedFromBackup = true
        try url.setResourceValues(resources)
        exportURL = url
    }
    func removeExport() {
        if let exportURL { try? FileManager.default.removeItem(at: exportURL) }
        exportURL = nil
    }
    func logout() async throws {
        var remoteError: Error?
        do { let _: EmptyReply = try await api().request("v1/auth/logout", method: "POST") }
        catch { remoteError = error }
        try SessionVault.clear()
        clearMemory()
        if remoteError != nil { notice = "Sessione rimossa da questo dispositivo. La revoca sul server non è stata confermata; la sessione remota scadrà automaticamente." }
    }
    func deleteAccount(password: String) async throws {
        let owner = identity?.id
        let api = try api()
        let origin = api.endpoint.absoluteString
        do {
            let _: EmptyReply = try await api.request("v1/me", method: "DELETE", body: Wire.encoder().encode(AccountDeletion(password: password, confirmed: true)))
        } catch let failure as ServiceError where failure.status == 401 {
            // Password verification and expired sessions both return 401. Check the session
            // before discarding it because of an incorrectly typed deletion password.
            let _: Identity = try await api.request("v1/me")
            throw ServiceError(status: 403, code: "password_verification", message: "Password non corretta. L'account non è stato eliminato.")
        }
        var cleanupFailed = false
        do { try await chatgpt.disconnectAll() } catch { cleanupFailed = true }
        let revocationMessage = chatgpt.message
        if let owner { do { try ChatGPTVault.forget(endpoint: origin, athleteID: owner) } catch { cleanupFailed = true } }
        do { try SessionVault.clear() } catch { cleanupFailed = true }
        clearMemory()
        notice = "Account e dati sul servizio eliminati. I dati originali in Apple Health rimangono disponibili."
        if cleanupFailed { notice! += " Pulizia del Portachiavi non confermata: riprova su dispositivo sbloccato." }
        if revocationMessage?.contains("non confermata") == true { notice! += " Revoca ChatGPT remota non confermata: gestisci il collegamento nelle impostazioni ChatGPT." }
    }
    private func clearMemory() {
        chatgpt.clearMemory()
        identity = nil; client = nil; review = nil; plan = nil; vendors = []
        profile = nil; profileChecked = false
        manualSessions = []
        healthPreview = []; pendingPlan = nil; invalidateReview(); removeExport()
        healthDetailCandidate = nil; healthDetails = [:]
    }
}
