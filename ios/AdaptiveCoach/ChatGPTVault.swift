import Foundation
import CryptoKit
import Security

struct ChatGPTCredential: Codable {
    let clientID: String
    let identity: ChatGPTAuthorization.Identity
    var accessToken: String
    var refreshToken: String?
    var idToken: String
    var scopes: [String]
    var expiresAt: Date
    var welcomed: Bool
    var nonce: String
    var permitsInference: Bool { Set(scopes).isSuperset(of: ["resource.invoke", "chatgpt.tokens.use.direct"]) }
}

struct ChatGPTRegistration: Codable, Identifiable {
    var id: String { clientID }
    let clientID: String
    let label: String
    var identity: ChatGPTAuthorization.Identity?
    var credential: ChatGPTCredential?
    var welcomed: Bool
}

// Pure registry: the issued client ID, rather than email or subject, identifies a registration.
struct ChatGPTAccountBook: Codable {
    var schemaVersion = 1
    private(set) var registrations: [ChatGPTRegistration] = []
    private(set) var activeClientID: String?
    private var nextLabel = 1

    var activeCredential: ChatGPTCredential? { registrations.first { $0.clientID == activeClientID }?.credential }
    func validate() throws {
        guard schemaVersion == 1, registrations.count <= 12, nextLabel > 0,
              Set(registrations.map(\.clientID)).count == registrations.count,
              Set(registrations.map(\.label)).count == registrations.count else { throw Self.failure() }
        for row in registrations {
            guard row.clientID.hasPrefix("oaiapp_"), row.clientID.count <= 200,
                  !row.label.isEmpty, row.label.count <= 100 else { throw Self.failure() }
            if let credential = row.credential {
                guard credential.clientID == row.clientID, credential.identity.subject == row.identity?.subject,
                      credential.welcomed == row.welcomed else { throw Self.failure() }
            }
        }
        if activeClientID != nil, activeCredential == nil { throw Self.failure() }
    }
    mutating func retainIssued(_ clientID: String) throws {
        guard clientID.hasPrefix("oaiapp_"), clientID.count <= 200 else { throw Self.failure() }
        if registrations.contains(where: { $0.clientID == clientID }) { return }
        guard registrations.count < 12, nextLabel < 10_000 else { throw Self.failure() }
        registrations.append(.init(clientID: clientID, label: "Account ChatGPT \(nextLabel)", identity: nil, credential: nil, welcomed: false))
        nextLabel += 1
    }
    mutating func accept(_ credential: ChatGPTCredential, activate: Bool = true) throws {
        try retainIssued(credential.clientID)
        guard let index = registrations.firstIndex(where: { $0.clientID == credential.clientID }),
              registrations[index].identity == nil || registrations[index].identity?.subject == credential.identity.subject else { throw Self.failure() }
        registrations[index].identity = credential.identity
        registrations[index].credential = credential
        registrations[index].welcomed = credential.welcomed
        if activate { activeClientID = credential.clientID }
        try validate()
    }
    mutating func signOut(_ clientID: String) {
        guard let index = registrations.firstIndex(where: { $0.clientID == clientID }) else { return }
        registrations[index].credential = nil
        if activeClientID == clientID { activeClientID = nil }
    }
    mutating func signOutAll() {
        for index in registrations.indices { registrations[index].credential = nil }
        activeClientID = nil
    }
    static func migrated(credential: ChatGPTCredential?, retryClient: String?) throws -> Self {
        var result = Self()
        if let credential { try result.accept(credential) }
        if let retryClient { try result.retainIssued(retryClient) }
        return result
    }
    private static func failure() -> ServiceError {
        ServiceError(status: 0, code: "chatgpt_registry", message: "Registro degli account ChatGPT non valido o pieno. Nessuna registrazione è stata sostituita.")
    }
}

enum ChatGPTVault {
    static func binding(endpoint: String, athleteID: String) -> String {
        ChatGPTAuthorization.base64URL(Data(SHA256.hash(data: Data((endpoint + "\n" + athleteID).utf8))))
    }
    static func hostID() throws -> String {
        if let existing: String = try read(account: "host") { return existing }
        let value = "urn:uuid:" + UUID().uuidString.lowercased()
        try save(value, account: "host")
        return value
    }
    static func book(_ binding: String) throws -> ChatGPTAccountBook {
        if let existing: ChatGPTAccountBook = try read(account: "registry-" + binding) {
            try existing.validate(); return existing
        }
        let legacy: ChatGPTCredential? = try read(account: "account-" + binding)
        let retry: String? = try read(account: "retry-" + binding)
        let result = try ChatGPTAccountBook.migrated(credential: legacy, retryClient: retry)
        if legacy != nil || retry != nil {
            try saveBook(result, binding: binding)
            // Only remove legacy items after the replacement is durably written.
            try remove(account: "account-" + binding); try remove(account: "retry-" + binding)
        }
        return result
    }
    static func saveBook(_ book: ChatGPTAccountBook, binding: String) throws {
        try book.validate(); try save(book, account: "registry-" + binding)
    }
    static func forget(endpoint: String, athleteID: String) throws { try clear(binding(endpoint: endpoint, athleteID: athleteID)) }
    static func clear(_ binding: String) throws {
        for prefix in ["registry-", "account-", "retry-"] { try remove(account: prefix + binding) }
    }
    private static func remove(account: String) throws {
        let status = SecItemDelete(query(account) as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else { throw failure() }
    }
    private static func query(_ account: String) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: "EnduranceCoach.ChatGPT",
         kSecAttrAccount as String: account]
    }
    private static func read<T: Decodable>(account: String) throws -> T? {
        var lookup = query(account)
        lookup[kSecReturnData as String] = true; lookup[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        let status = SecItemCopyMatching(lookup as CFDictionary, &result)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess, let data = result as? Data, data.count <= 1_500_000 else { throw failure() }
        return try JSONDecoder().decode(T.self, from: data)
    }
    private static func save<T: Encodable>(_ value: T, account: String) throws {
        let data = try JSONEncoder().encode(value)
        guard data.count <= 1_500_000 else { throw failure() }
        let attributes: [String: Any] = [kSecValueData as String: data,
                                       kSecAttrAccessible as String: kSecAttrAccessibleWhenUnlockedThisDeviceOnly]
        let status = SecItemUpdate(query(account) as CFDictionary, attributes as CFDictionary)
        if status == errSecItemNotFound {
            var insert = query(account); attributes.forEach { insert[$0.key] = $0.value }
            guard SecItemAdd(insert as CFDictionary, nil) == errSecSuccess else { throw failure() }
        } else if status != errSecSuccess { throw failure() }
    }
    private static func failure() -> ServiceError {
        ServiceError(status: 0, code: "chatgpt_vault", message: "Il collegamento ChatGPT non può essere custodito nel Portachiavi. Sblocca il dispositivo e riprova.")
    }
}
