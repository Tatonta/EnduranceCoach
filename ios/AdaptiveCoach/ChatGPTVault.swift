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
    static func credential(_ binding: String) throws -> ChatGPTCredential? { try read(account: "account-" + binding) }
    static func save(_ credential: ChatGPTCredential, binding: String) throws { try save(credential, account: "account-" + binding) }
    static func forget(endpoint: String, athleteID: String) throws { try clear(binding(endpoint: endpoint, athleteID: athleteID)) }
    static func clear(_ binding: String) throws {
        for prefix in ["account-", "retry-"] {
            let status = SecItemDelete(query(prefix + binding) as CFDictionary)
            guard status == errSecSuccess || status == errSecItemNotFound else { throw failure() }
        }
    }
    static func retryClient(_ binding: String) throws -> String? { try read(account: "retry-" + binding) }
    static func saveRetryClient(_ clientID: String, binding: String) throws { try save(clientID, account: "retry-" + binding) }
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
        guard status == errSecSuccess, let data = result as? Data else { throw failure() }
        return try JSONDecoder().decode(T.self, from: data)
    }
    private static func save<T: Encodable>(_ value: T, account: String) throws {
        let attributes: [String: Any] = [kSecValueData as String: try JSONEncoder().encode(value),
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
