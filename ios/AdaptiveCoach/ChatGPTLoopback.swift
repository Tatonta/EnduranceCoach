import Foundation
import Network

final class ChatGPTLoopback {
    private var listener: NWListener?
    private let queue = DispatchQueue(label: "EnduranceCoach.ChatGPT.loopback")
    private var connections: [UUID: NWConnection] = [:]
    private var port: UInt16 = 0
    private var callback: ((URL) -> Bool)?
    private var starting: CheckedContinuation<UInt16, Error>?

    func start(callback: @escaping (URL) -> Bool) async throws -> UInt16 {
        let parameters = NWParameters.tcp
        parameters.requiredLocalEndpoint = .hostPort(host: "127.0.0.1", port: .any)
        let server = try NWListener(using: parameters)
        self.listener = server; self.callback = callback
        return try await withCheckedThrowingContinuation { continuation in
            starting = continuation
            server.stateUpdateHandler = { [weak self] state in
                guard let self else { return }
                switch state {
                case .ready:
                    guard let value = self.listener?.port?.rawValue, value > 0 else { self.failStart(); return }
                    self.port = value; self.starting?.resume(returning: value); self.starting = nil
                case .failed: self.failStart()
                default: break
                }
            }
            server.newConnectionHandler = { [weak self] connection in
                guard let self else { connection.cancel(); return }; self.accept(connection)
            }
            server.start(queue: queue)
        }
    }
    func stop() {
        queue.async { [self] in
            self.listener?.cancel(); self.listener = nil
            self.connections.values.forEach { $0.cancel() }; self.connections = [:]; self.callback = nil
            self.starting?.resume(throwing: ChatGPTAuthorization.failure()); self.starting = nil
        }
    }
    func setCallback(_ callback: @escaping (URL) -> Bool) {
        queue.async { [weak self] in self?.callback = callback }
    }
    private func failStart() {
        starting?.resume(throwing: ChatGPTAuthorization.failure()); starting = nil
        listener?.cancel(); listener = nil
    }
    private func accept(_ connection: NWConnection) {
        guard connections.count < 4 else { connection.cancel(); return }
        let identifier = UUID(); connections[identifier] = connection
        connection.start(queue: queue)
        queue.asyncAfter(deadline: .now() + 5) { [weak self, weak connection] in
            connection?.cancel(); self?.connections.removeValue(forKey: identifier)
        }
        receive(connection, identifier: identifier, collected: Data())
    }
    private func receive(_ connection: NWConnection, identifier: UUID, collected: Data) {
        connection.receive(minimumIncompleteLength: 1, maximumLength: 8192) { [weak self] data, _, complete, error in
            guard let self else { return }
            let body = collected + (data ?? Data())
            guard body.count <= 16_384, error == nil else { self.reply(connection, identifier: identifier, accepted: false); return }
            if body.range(of: Data("\r\n\r\n".utf8)) != nil {
                guard let text = String(data: body, encoding: .utf8), let request = text.components(separatedBy: "\r\n").first,
                      let url = Self.requestURL(request, port: self.port) else { self.reply(connection, identifier: identifier, accepted: false); return }
                self.reply(connection, identifier: identifier, accepted: self.callback?(url) == true)
            } else if !complete { self.receive(connection, identifier: identifier, collected: body) }
            else { self.reply(connection, identifier: identifier, accepted: false) }
        }
    }
    static func requestURL(_ requestLine: String, port: UInt16) -> URL? {
        let parts = requestLine.split(separator: " ", omittingEmptySubsequences: false)
        guard parts.count == 3, parts[0] == "GET", ["HTTP/1.0", "HTTP/1.1"].contains(String(parts[2])),
              parts[1].hasPrefix("/auth/callback?"), parts[1].count <= 12_000 else { return nil }
        return URL(string: "http://127.0.0.1:\(port)" + String(parts[1]))
    }
    private func reply(_ connection: NWConnection, identifier: UUID, accepted: Bool) {
        let text = accepted ? "Collegamento ricevuto. Puoi tornare a EnduranceCoach." : "Richiesta non valida. Torna a EnduranceCoach e riprova."
        let response = "HTTP/1.1 \(accepted ? "200 OK" : "400 Bad Request")\r\nContent-Type: text/plain; charset=utf-8\r\nContent-Length: \(text.utf8.count)\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n\(text)"
        connection.send(content: Data(response.utf8), completion: .contentProcessed { [weak self] _ in
            connection.cancel(); self?.connections.removeValue(forKey: identifier)
        })
    }
}
