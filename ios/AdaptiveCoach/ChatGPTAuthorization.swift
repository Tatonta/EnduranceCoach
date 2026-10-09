import Foundation
import CryptoKit
import Security

enum ChatGPTAuthorization {
    static let issuer = "https://auth.openai.com"
    static let resource = "https://api.openai.com/v1"
    static let scopes = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"

    struct Attempt {
        let state: String
        let nonce: String
        let verifier: String
        let redirectURI: URL
        let clientID: String
        let expiresAt: Date

        init(port: UInt16, clientID: String = "dynamic_agent_client", now: Date = Date()) throws {
            guard port > 0 else { throw failure() }
            state = try random(); nonce = try random(); verifier = try random(bytes: 64)
            redirectURI = URL(string: "http://127.0.0.1:\(port)/auth/callback")!
            self.clientID = clientID
            expiresAt = now.addingTimeInterval(600)
        }

        func authorizationURL(hostID: String, idTokenHint: String? = nil) throws -> URL {
            guard hostID.hasPrefix("urn:uuid:"), UUID(uuidString: String(hostID.dropFirst(9))) != nil else { throw failure() }
            var query = ["client_id": clientID, "response_type": "code", "redirect_uri": redirectURI.absoluteString,
                         "scope": scopes, "resource": resource, "state": state, "nonce": nonce,
                         "code_challenge_method": "S256", "code_challenge": challenge(verifier),
                         "ext_agent_host_id": hostID]
            if clientID == "dynamic_agent_client" { query["agent_name_hint"] = "EnduranceCoach" }
            if let idTokenHint, clientID != "dynamic_agent_client" { query["id_token_hint"] = idTokenHint }
            var parts = URLComponents(string: issuer + "/api/accounts/authorize")!
            parts.queryItems = query.sorted { $0.key < $1.key }.map { URLQueryItem(name: $0.key, value: $0.value) }
            return try parts.url.unwrap()
        }

        func callback(_ url: URL, now: Date = Date()) throws -> (code: String, clientID: String) {
            guard now < expiresAt, let parts = URLComponents(url: url, resolvingAgainstBaseURL: false),
                  parts.scheme == "http", parts.host == "127.0.0.1", parts.port == redirectURI.port,
                  parts.path == "/auth/callback", parts.user == nil, parts.password == nil, parts.fragment == nil else { throw failure() }
            var query: [String: String] = [:]
            for item in parts.queryItems ?? [] {
                guard query[item.name] == nil, let value = item.value else { throw failure() }
                query[item.name] = value
            }
            guard query["state"] == state else { throw failure() }
            if query["error"] != nil { throw ServiceError(status: 0, code: "chatgpt_cancelled", message: "Collegamento ChatGPT annullato o permesso non concesso.") }
            let issued = query["client_id"] ?? clientID
            guard issued.hasPrefix("oaiapp_"), issued.count <= 200,
                  clientID == "dynamic_agent_client" || issued == clientID,
                  let code = query["code"], !code.isEmpty, code.count <= 4096 else { throw failure() }
            return (code, issued)
        }
    }

    struct Identity: Codable {
        let subject: String
        let email: String?
    }

    static func random(bytes: Int = 32) throws -> String {
        var value = [UInt8](repeating: 0, count: bytes)
        guard SecRandomCopyBytes(kSecRandomDefault, value.count, &value) == errSecSuccess else { throw failure() }
        return base64URL(Data(value))
    }
    static func base64URL(_ value: Data) -> String {
        value.base64EncodedString().replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "")
    }
    static func decode(_ value: String) throws -> Data {
        guard value.count <= 32_768, value.allSatisfy({ $0.isASCII && ($0.isLetter || $0.isNumber || $0 == "-" || $0 == "_") }) else { throw failure() }
        let text = value.replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
        return try Data(base64Encoded: text + String(repeating: "=", count: (4 - text.count % 4) % 4)).unwrap()
    }
    static func challenge(_ verifier: String) -> String { base64URL(Data(SHA256.hash(data: Data(verifier.utf8)))) }

    static func validateIDToken(_ token: String, jwks: Data, clientID: String, nonce: String, now: Date = Date()) throws -> Identity {
        guard token.utf8.count <= 32_768, jwks.count <= 262_144 else { throw failure() }
        let pieces = token.split(separator: ".", omittingEmptySubsequences: false).map(String.init)
        guard pieces.count == 3,
              let header = try JSONSerialization.jsonObject(with: decode(pieces[0])) as? [String: Any],
              header["alg"] as? String == "RS256", let kid = header["kid"] as? String,
              let document = try JSONSerialization.jsonObject(with: jwks) as? [String: Any],
              let keys = document["keys"] as? [[String: Any]], keys.count <= 100 else { throw failure() }
        let matches = keys.filter { $0["kid"] as? String == kid && $0["kty"] as? String == "RSA" }
        guard matches.count == 1, let n = matches[0]["n"] as? String, let e = matches[0]["e"] as? String,
              matches[0]["use"] == nil || matches[0]["use"] as? String == "sig",
              matches[0]["alg"] == nil || matches[0]["alg"] as? String == "RS256" else { throw failure() }
        let modulus = try decode(n), exponent = try decode(e)
        guard (256...1024).contains(modulus.count), (1...8).contains(exponent.count) else { throw failure() }
        let encoded = sequence(integer(modulus) + integer(exponent))
        var error: Unmanaged<CFError>?
        guard let key = SecKeyCreateWithData(encoded as CFData,
                                             [kSecAttrKeyType: kSecAttrKeyTypeRSA, kSecAttrKeyClass: kSecAttrKeyClassPublic] as CFDictionary, &error),
              SecKeyVerifySignature(key, .rsaSignatureMessagePKCS1v15SHA256, Data((pieces[0] + "." + pieces[1]).utf8) as CFData,
                                    try decode(pieces[2]) as CFData, &error),
              let claims = try JSONSerialization.jsonObject(with: decode(pieces[1])) as? [String: Any] else { throw failure() }
        let audiences = (claims["aud"] as? [String]) ?? (claims["aud"] as? String).map { [$0] } ?? []
        guard claims["iss"] as? String == issuer, audiences.contains(clientID), claims["nonce"] as? String == nonce,
              let expiry = claims["exp"] as? Double, expiry.isFinite, expiry > now.timeIntervalSince1970,
              let issued = claims["iat"] as? Double, issued.isFinite, issued <= now.timeIntervalSince1970 + 5,
              let subject = claims["sub"] as? String, !subject.isEmpty, subject.count <= 500 else { throw failure() }
        return Identity(subject: subject, email: claims["email"] as? String)
    }

    private static func integer(_ input: Data) -> Data {
        var bytes = Array(input)
        while bytes.count > 1 && bytes[0] == 0 { bytes.removeFirst() }
        if bytes.first.map({ $0 & 0x80 != 0 }) == true { bytes.insert(0, at: 0) }
        return Data([0x02]) + length(bytes.count) + Data(bytes)
    }
    private static func sequence(_ input: Data) -> Data { Data([0x30]) + length(input.count) + input }
    private static func length(_ value: Int) -> Data {
        if value < 128 { return Data([UInt8(value)]) }
        var number = value, bytes: [UInt8] = []
        while number > 0 { bytes.insert(UInt8(number & 255), at: 0); number >>= 8 }
        return Data([0x80 | UInt8(bytes.count)]) + Data(bytes)
    }
    static func failure() -> ServiceError { ServiceError(status: 401, code: "chatgpt_authorization", message: "Autorizzazione ChatGPT non valida. Ripeti il collegamento.") }
}

private extension Optional {
    func unwrap() throws -> Wrapped {
        guard let value = self else { throw ChatGPTAuthorization.failure() }
        return value
    }
}
