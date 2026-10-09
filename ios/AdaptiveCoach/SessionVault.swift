import Foundation
import Security

enum SessionVault {
    private static var query: [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: "AdaptiveCoach.session",
         kSecAttrAccount as String: "current"]
    }
    static func read() throws -> SessionSecret? {
        var lookup = query
        lookup[kSecReturnData as String] = true
        lookup[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        let status = SecItemCopyMatching(lookup as CFDictionary, &result)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess, let data = result as? Data else { throw vaultError(status) }
        return try JSONDecoder().decode(SessionSecret.self, from: data)
    }
    static func write(_ secret: SessionSecret) throws {
        // Update in place rather than deleting a usable session before a failed write.
        let data = try JSONEncoder().encode(secret)
        let attributes: [String: Any] = [kSecValueData as String: data,
            kSecAttrAccessible as String: kSecAttrAccessibleWhenUnlockedThisDeviceOnly]
        let status = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
        if status == errSecItemNotFound {
            var insert = query
            attributes.forEach { insert[$0.key] = $0.value }
            let inserted = SecItemAdd(insert as CFDictionary, nil)
            guard inserted == errSecSuccess else { throw vaultError(inserted) }
        } else if status != errSecSuccess { throw vaultError(status) }
    }
    static func clear() throws {
        let status = SecItemDelete(query as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else { throw vaultError(status) }
    }
    private static func vaultError(_ status: OSStatus) -> ServiceError {
        if status == errSecMissingEntitlement {
            return ServiceError(status: 0, code: "keychain_configuration", message: "L'app non riesce a proteggere la sessione. Aggiorna l'app o contatta l'assistenza.")
        }
        return ServiceError(status: 0, code: "keychain", message: "Sessione nel Portachiavi non disponibile (\(status)). Sblocca il dispositivo e riprova.")
    }
}
