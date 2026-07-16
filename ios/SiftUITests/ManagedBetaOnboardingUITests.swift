import Network
import XCTest

final class ManagedBetaOnboardingUITests: XCTestCase {
    private var server: LocalHTTPServer!

    override func setUpWithError() throws {
        continueAfterFailure = false
        server = try LocalHTTPServer()
        try server.start()
    }

    override func tearDownWithError() throws {
        server.stop()
        server = nil
    }

    func testCleanInstallActivationConnectsProviderAndCreatesFirstConcept() throws {
        let app = XCUIApplication()
        app.launchEnvironment["SIFT_MANAGED_BETA"] = "1"
        app.launchEnvironment["SIFT_BACKEND_BASE_URL"] = "http://127.0.0.1:\(server.port)"
        app.launchEnvironment["SIFT_UI_TEST_RESET_MANAGED_CREDENTIALS"] = "1"
        app.launchEnvironment["SIFT_UI_TEST_IN_MEMORY"] = "1"
        app.launchEnvironment["SIFT_UI_TEST_IN_MEMORY_CREDENTIALS"] = "1"
        app.launch()

        let inviteCode = app.textFields["managed.inviteCode"]
        XCTAssertTrue(inviteCode.waitForExistence(timeout: 5))
        inviteCode.tap()
        inviteCode.typeText("ui-test-invite")
        app.buttons["managed.activate"].tap()

        let providerKey = app.secureTextFields["managed.providerKey"]
        XCTAssertTrue(providerKey.waitForExistence(timeout: 5))
        providerKey.tap()
        providerKey.typeText("sk-ui-test-secret")
        app.buttons["managed.connect"].tap()

        let captureInput = app.textFields["capture.input"]
        XCTAssertTrue(
            captureInput.waitForExistence(timeout: 5),
            "Requests: \(server.receivedRequests)\nUI: \(app.debugDescription)"
        )
        captureInput.tap()
        captureInput.typeText("Explain durable UI testing")
        app.buttons["capture.submit"].tap()

        XCTAssertTrue(app.staticTexts["UI Test Concept"].waitForExistence(timeout: 10))
    }
}

private final class LocalHTTPServer: @unchecked Sendable {
    private let listener: NWListener
    private let queue = DispatchQueue(label: "app.sift.ui-test-http")
    private let lock = NSLock()
    private var connections: [NWConnection] = []
    private var requests: [String] = []
    private(set) var port: UInt16 = 0

    var receivedRequests: [String] {
        lock.lock()
        defer { lock.unlock() }
        return requests
    }

    init() throws {
        listener = try NWListener(using: .tcp, on: .any)
    }

    func start() throws {
        let ready = DispatchSemaphore(value: 0)
        var startError: NWError?
        listener.stateUpdateHandler = { [weak self] state in
            switch state {
            case .ready:
                self?.port = self?.listener.port?.rawValue ?? 0
                ready.signal()
            case .failed(let error):
                startError = error
                ready.signal()
            default:
                break
            }
        }
        listener.newConnectionHandler = { [weak self] connection in
            self?.accept(connection)
        }
        listener.start(queue: queue)
        guard ready.wait(timeout: .now() + 5) == .success else {
            throw ServerError.startTimedOut
        }
        if let startError {
            throw startError
        }
        guard port != 0 else {
            throw ServerError.missingPort
        }
    }

    func stop() {
        listener.cancel()
        lock.lock()
        let activeConnections = connections
        connections.removeAll()
        lock.unlock()
        activeConnections.forEach { $0.cancel() }
    }

    private func accept(_ connection: NWConnection) {
        lock.lock()
        connections.append(connection)
        lock.unlock()
        connection.start(queue: queue)
        receiveRequest(on: connection, accumulated: Data())
    }

    private func receiveRequest(on connection: NWConnection, accumulated: Data) {
        connection.receive(minimumIncompleteLength: 1, maximumLength: 64 * 1024) {
            [weak self] data, _, isComplete, error in
            guard let self else { return }
            var requestData = accumulated
            if let data {
                requestData.append(data)
            }
            if self.isCompleteHTTPRequest(requestData) || isComplete {
                self.respond(to: requestData, on: connection)
            } else if error == nil {
                self.receiveRequest(on: connection, accumulated: requestData)
            } else {
                connection.cancel()
            }
        }
    }

    private func isCompleteHTTPRequest(_ data: Data) -> Bool {
        guard let request = String(data: data, encoding: .utf8),
              let headerRange = request.range(of: "\r\n\r\n") else {
            return false
        }
        let headers = String(request[..<headerRange.lowerBound])
        let contentLength = headers
            .components(separatedBy: "\r\n")
            .first { $0.lowercased().hasPrefix("content-length:") }
            .flatMap { line in
                Int(line.split(separator: ":", maxSplits: 1)[1].trimmingCharacters(in: .whitespaces))
            }
            ?? 0
        let bodyLength = request[headerRange.upperBound...].utf8.count
        return bodyLength >= contentLength
    }

    private func respond(to requestData: Data, on connection: NWConnection) {
        let request = String(data: requestData, encoding: .utf8) ?? ""
        let requestLine = request.components(separatedBy: "\r\n").first ?? ""
        let parts = requestLine.split(separator: " ")
        let method = parts.first.map(String.init) ?? "GET"
        let path = parts.count > 1 ? String(parts[1]) : "/"
        lock.lock()
        requests.append("\(method) \(path)")
        lock.unlock()
        let response = response(method: method, path: path)
        let header = "HTTP/1.1 \(response.status)\r\nContent-Type: \(response.contentType)\r\nContent-Length: \(response.body.utf8.count)\r\nConnection: close\r\n\r\n"
        connection.send(content: Data((header + response.body).utf8), completion: .contentProcessed { _ in
            connection.cancel()
        })
    }

    private func response(method: String, path: String) -> HTTPResponse {
        if method == "POST", path == "/v1/beta/activate" {
            return .json("""
            {"betaAccessToken":"ui-test-token","ownerId":"00000000-0000-0000-0000-000000000001","expiresAt":"2033-01-01T00:00:00Z"}
            """)
        }
        if method == "GET", path == "/v1/runtime/model-providers" {
            return .json("""
            {"providers":[{"id":"openai","name":"OpenAI","description":"UI test provider","adapter":"openai","exposureTier":"stable","defaultBaseURL":"https://api.openai.com/v1","defaultModel":"gpt-ui-test","requiresApiKey":true,"supportsModelListing":false,"status":"available","isAdvanced":false}]}
            """)
        }
        if method == "POST", path == "/v1/providers/test" {
            return .json("{\"ok\":true}")
        }
        if method == "PUT", path == "/v1/provider-connection" {
            return .json(providerConnection)
        }
        if method == "GET", path == "/v1/provider-connection" {
            return .json(providerConnection)
        }
        if method == "GET", path == "/v1/app-status" {
            return .json("""
            {"env":"ui-test","modelProvider":"openai","explainModel":"gpt-ui-test","webSearchEnabled":true,"databaseURL":"managed","providerBaseURL":"https://api.openai.com/v1","apiKeyConfigured":true}
            """)
        }
        if method == "GET", path == "/v1/concepts" {
            return .json("[]")
        }
        if method == "POST", path == "/v1/concepts/stream" {
            let body = [
                "{\"type\":\"started\"}",
                "{\"type\":\"delta\",\"delta\":\"A durable UI test answer.\"}",
                "{\"type\":\"completed\",\"concept\":\(conceptJSON)}"
            ].joined(separator: "\n") + "\n"
            return HTTPResponse(status: "200 OK", contentType: "application/x-ndjson", body: body)
        }
        if method == "GET", path.hasPrefix("/v1/concepts/"), path.hasSuffix("/turns") {
            return .json("[]")
        }
        if method == "GET", path.hasPrefix("/v1/concepts/") {
            return .json(conceptJSON)
        }
        return HTTPResponse(status: "404 Not Found", contentType: "application/json", body: "{\"detail\":\"not found\"}")
    }

    private var providerConnection: String {
        "{\"providerId\":\"openai\",\"baseURL\":\"https://api.openai.com/v1\",\"model\":\"gpt-ui-test\"}"
    }

    private var conceptJSON: String {
        """
        {"id":"00000000-0000-0000-0000-000000000101","canonicalTitle":"ui-test-concept","displayTitle":"UI Test Concept","oneLineExplanation":"Generated through the managed beta UI journey.","initialAnswer":"A durable UI test answer.","maturity":"initial","captureStatus":"ready","noteRevision":1,"blocks":[],"tags":[],"topics":[],"relations":[]}
        """
    }
}

private struct HTTPResponse {
    var status: String
    var contentType: String
    var body: String

    static func json(_ body: String) -> HTTPResponse {
        HTTPResponse(status: "200 OK", contentType: "application/json", body: body)
    }
}

private enum ServerError: Error {
    case startTimedOut
    case missingPort
}
