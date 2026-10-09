import Foundation
import SwiftUI
import AuthenticationServices
import UIKit

private final class CallbackGate {
    private let lock = NSLock()
    private var consumed = false
    func consume(_ action: () throws -> Void) -> Bool {
        lock.lock(); defer { lock.unlock() }
        guard !consumed else { return false }
        do { try action(); consumed = true; return true } catch { return false }
    }
}

@MainActor
final class ChatGPTConnection: NSObject, ObservableObject, ASWebAuthenticationPresentationContextProviding {
    @Published private(set) var credential: ChatGPTCredential?
    @Published private(set) var connecting = false
    @Published var message: String?
    @Published var needsWelcome = false
    private var binding: String?
    private var browser: ASWebAuthenticationSession?
    private var listener: ChatGPTLoopback?
    private var timeout: Task<Void, Never>?
    private var generation = UUID()
    private var waitingForCallback = false
    private var renewal: Task<String, Error>?
    private let http = ChatGPTHTTP()

    func load(endpoint: String, athleteID: String) throws {
        clearMemory()
        let key = ChatGPTVault.binding(endpoint: endpoint, athleteID: athleteID)
        binding = key; credential = try ChatGPTVault.credential(key)
        needsWelcome = credential?.permitsInference == true && credential?.welcomed == false
    }
    func clearMemory() {
        generation = UUID(); timeout?.cancel(); timeout = nil; renewal?.cancel(); renewal = nil
        listener?.stop(); listener = nil; browser?.cancel(); browser = nil
        connecting = false; waitingForCallback = false; binding = nil; credential = nil; message = nil; needsWelcome = false
    }
    func connect() async {
        guard !connecting, let binding else { return }
        connecting = true; waitingForCallback = true; message = "Apri il tuo account ChatGPT e controlla i permessi richiesti."
        let attemptID = UUID(); generation = attemptID
        do {
            let host = try ChatGPTVault.hostID()
            let loopback = ChatGPTLoopback(); listener = loopback
            let port = try await loopback.start { _ in false }
            guard generation == attemptID, self.binding == binding else { loopback.stop(); return }
            let savedClient = try ChatGPTVault.retryClient(binding)
            let attempt = try ChatGPTAuthorization.Attempt(port: port, clientID: credential?.clientID ?? savedClient ?? "dynamic_agent_client")
            let gate = CallbackGate()
            loopback.setCallback { [weak self] url in
                gate.consume {
                    do {
                        let result = try attempt.callback(url)
                        Task { @MainActor [weak self] in await self?.finish(result, attempt: attempt, binding: binding, attemptID: attemptID) }
                    } catch let error as ServiceError where error.code == "chatgpt_cancelled" {
                        Task { @MainActor [weak self] in self?.cancel(message: error.localizedDescription) }
                    }
                }
            }
            let url = try attempt.authorizationURL(hostID: host, idTokenHint: credential?.idToken)
            // HTTP loopback is received by our listener; no custom scheme or HTTPS callback is substituted.
            let session = ASWebAuthenticationSession(url: url, callbackURLScheme: nil) { [weak self] _, error in
                Task { @MainActor [weak self] in
                    guard let self, self.generation == attemptID, self.waitingForCallback, error != nil else { return }
                    self.cancel(message: "Collegamento ChatGPT annullato.")
                }
            }
            session.presentationContextProvider = self
            session.prefersEphemeralWebBrowserSession = true
            browser = session
            guard session.start() else { throw ChatGPTAuthorization.failure() }
            timeout = Task { [weak self] in
                try? await Task.sleep(for: .seconds(600))
                guard !Task.isCancelled, let self, self.generation == attemptID else { return }
                self.cancel(message: "Collegamento scaduto. Riparti da Continue with ChatGPT.")
            }
        } catch { if generation == attemptID { cancel(message: error.localizedDescription) } }
    }
    private func finish(_ result: (code: String, clientID: String), attempt: ChatGPTAuthorization.Attempt, binding: String, attemptID: UUID) async {
        guard generation == attemptID, self.binding == binding else { return }
        waitingForCallback = false; timeout?.cancel(); listener?.stop(); browser?.cancel(); browser = nil
        message = "Verifica del collegamento ChatGPT…"
        do {
            try ChatGPTVault.saveRetryClient(result.clientID, binding: binding)
            let token = try await http.token(["grant_type": "authorization_code", "client_id": result.clientID,
                                             "code": result.code, "code_verifier": attempt.verifier,
                                             "redirect_uri": attempt.redirectURI.absoluteString, "resource": ChatGPTAuthorization.resource])
            guard let idToken = token.idToken else { throw ChatGPTAuthorization.failure() }
            let identity = try await http.identity(idToken, clientID: result.clientID, nonce: attempt.nonce)
            guard generation == attemptID, self.binding == binding,
                  credential == nil || credential?.identity.subject == identity.subject else { throw ChatGPTAuthorization.failure() }
            let value = ChatGPTCredential(clientID: result.clientID, identity: identity, accessToken: token.accessToken,
                                          refreshToken: token.refreshToken, idToken: idToken,
                                          scopes: token.scope.split(separator: " ").map(String.init),
                                          expiresAt: Date().addingTimeInterval(token.expiresIn), welcomed: credential?.welcomed ?? false, nonce: attempt.nonce)
            try ChatGPTVault.save(value, binding: binding); credential = value
            needsWelcome = value.permitsInference && !value.welcomed
            message = value.permitsInference ? "Account collegato con permesso di usare il piano ChatGPT." : "Identità collegata. Il permesso di usare il piano ChatGPT non è attivo."
        } catch { if generation == attemptID { message = error.localizedDescription } }
        if generation == attemptID { connecting = false }
    }
    func acknowledgeWelcome() throws {
        guard let binding, var value = credential else { return }
        value.welcomed = true; try ChatGPTVault.save(value, binding: binding)
        credential = value; needsWelcome = false
    }
    func disconnect() async throws {
        guard let binding else { return }
        let value = credential
        clearMemory()
        try ChatGPTVault.clear(binding)
        if let value { try ChatGPTVault.saveRetryClient(value.clientID, binding: binding) }
        self.binding = binding
        let current = generation
        if let value {
            do {
                _ = try await http.request(url: URL(string: ChatGPTAuthorization.issuer + "/api/accounts/oauth/revoke")!, method: "POST",
                                           form: ["client_id": value.clientID, "token": value.refreshToken ?? value.accessToken,
                                                  "token_type_hint": value.refreshToken == nil ? "access_token" : "refresh_token"])
                if generation == current { message = "Account ChatGPT scollegato." }
            } catch { if generation == current { message = "Sessione locale rimossa; revoca remota non confermata. Gestisci il collegamento nelle impostazioni ChatGPT." } }
        }
    }
    private func cancel(message: String) {
        generation = UUID(); connecting = false; waitingForCallback = false; timeout?.cancel(); timeout = nil
        listener?.stop(); listener = nil; browser?.cancel(); browser = nil; self.message = message
    }
    func accessToken() async throws -> String {
        if let renewal { return try await renewal.value }
        let task = Task { @MainActor [weak self] in
            guard let self else { throw ChatGPTAuthorization.failure() }
            return try await self.renewAccessToken()
        }
        renewal = task
        defer { renewal = nil }
        return try await task.value
    }
    private func renewAccessToken() async throws -> String {
        guard let binding, var value = credential, value.permitsInference, value.welcomed else { throw ChatGPTAuthorization.failure() }
        let current = generation
        if value.expiresAt.timeIntervalSinceNow < 60 {
            guard let refresh = value.refreshToken else { throw ChatGPTAuthorization.failure() }
            let renewed = try await http.token(["grant_type": "refresh_token", "client_id": value.clientID,
                                                "refresh_token": refresh, "resource": ChatGPTAuthorization.resource])
            if let idToken = renewed.idToken {
                let identity = try await http.identity(idToken, clientID: value.clientID, nonce: value.nonce)
                guard identity.subject == value.identity.subject else { throw ChatGPTAuthorization.failure() }
                value.idToken = idToken
            }
            value.accessToken = renewed.accessToken; value.refreshToken = renewed.refreshToken ?? value.refreshToken
            value.expiresAt = Date().addingTimeInterval(renewed.expiresIn); value.scopes = renewed.scope.split(separator: " ").map(String.init)
            guard generation == current, self.binding == binding, value.permitsInference else { throw ChatGPTAuthorization.failure() }
            try ChatGPTVault.save(value, binding: binding); credential = value
        }
        return value.accessToken
    }
    var accountGeneration: UUID { generation }
    func presentationAnchor(for session: ASWebAuthenticationSession) -> ASPresentationAnchor {
        UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
            .filter { $0.activationState == .foregroundActive }.flatMap { $0.windows }
            .first { $0.isKeyWindow } ?? ASPresentationAnchor()
    }
}
