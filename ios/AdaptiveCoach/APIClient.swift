import Foundation

struct ServiceError: LocalizedError {
    let status: Int
    let code: String
    let message: String
    var errorDescription: String? { message }
}
private struct ErrorReply: Decodable { let detail: String; let code: String? }

enum Endpoint {
    static func validate(_ text: String) throws -> URL {
        guard let url = URL(string: text.trimmingCharacters(in: .whitespacesAndNewlines)),
              let parts = URLComponents(url: url, resolvingAgainstBaseURL: false),
              let host = parts.host, !host.isEmpty, parts.user == nil, parts.password == nil,
              parts.query == nil, parts.fragment == nil,
              parts.path.isEmpty || parts.path == "/" else {
            throw ServiceError(status: 0, code: "endpoint", message: "Inserisci l'origine HTTPS del servizio, senza percorso, credenziali o parametri.")
        }
        if parts.scheme == "https" { return url }
        #if DEBUG && targetEnvironment(simulator)
        if parts.scheme == "http", ["localhost", "127.0.0.1", "::1"].contains(host) { return url }
        #endif
        throw ServiceError(status: 0, code: "endpoint", message: "Il servizio deve usare HTTPS. HTTP locale è disponibile solo nel simulatore Debug.")
    }
}

// Ephemeral transport avoids writing authenticated responses or cookies to disk.
// The service origin is set only while signed out; tokens cannot be forwarded to another origin.
final class APIClient {
    let endpoint: URL
    var token: String?
    private let session: URLSession
    init(endpoint: URL, token: String? = nil, protocolClasses: [AnyClass]? = nil) {
        self.endpoint = endpoint
        self.token = token
        let config = URLSessionConfiguration.ephemeral
        config.urlCache = nil
        config.httpCookieStorage = nil
        config.httpShouldSetCookies = false
        config.requestCachePolicy = .reloadIgnoringLocalCacheData
        config.timeoutIntervalForRequest = 30
        config.timeoutIntervalForResource = 60
        if let protocolClasses { config.protocolClasses = protocolClasses }
        session = URLSession(configuration: config, delegate: RejectRedirects(), delegateQueue: nil)
    }
    func request<T: Decodable>(_ path: String, method: String = "GET", body: Data? = nil) async throws -> T {
        let data = try await raw(path, method: method, body: body)
        if data.isEmpty, T.self == EmptyReply.self { return EmptyReply() as! T }
        return try Wire.decoder().decode(T.self, from: data)
    }
    func raw(_ path: String, method: String = "GET", body: Data? = nil) async throws -> Data {
        var request = URLRequest(url: endpoint.appendingPathComponent(path))
        request.httpMethod = method
        request.httpBody = body
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if body != nil { request.setValue("application/json", forHTTPHeaderField: "Content-Type") }
        if let token { request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw URLError(.badServerResponse) }
        guard (200..<300).contains(http.statusCode) else {
            let reply = try? Wire.decoder().decode(ErrorReply.self, from: data)
            throw ServiceError(status: http.statusCode, code: reply?.code ?? "http_error",
                               message: reply?.detail ?? "Il servizio ha risposto con errore \(http.statusCode).")
        }
        return data
    }
}

private final class RejectRedirects: NSObject, URLSessionTaskDelegate {
    func urlSession(_ session: URLSession, task: URLSessionTask,
                    willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest,
                    completionHandler: @escaping (URLRequest?) -> Void) {
        // A reverse proxy must serve this exact origin directly. Never follow redirects with a bearer token.
        completionHandler(nil)
    }
}
