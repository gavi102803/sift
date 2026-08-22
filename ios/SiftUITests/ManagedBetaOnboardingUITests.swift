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

    func testCaptureScreenDoesNotScrollVertically() throws {
        let app = XCUIApplication()
        app.launchEnvironment["SIFT_BACKEND_BASE_URL"] = "http://127.0.0.1:\(server.port)"
        app.launchEnvironment["SIFT_UI_TEST_IN_MEMORY"] = "1"
        app.launch()

        let heading = app.staticTexts["What new concept did you hear?"]
        XCTAssertTrue(heading.waitForExistence(timeout: 5))
        let initialY = heading.frame.minY

        app.swipeUp()
        XCTAssertEqual(heading.frame.minY, initialY, accuracy: 1)
        app.swipeDown()
        XCTAssertEqual(heading.frame.minY, initialY, accuracy: 1)
    }

    func testInitialModelRunCompletesAfterAppTerminationAndReconcilesOnRelaunch() throws {
        server.setRunCompleted(false)
        let app = XCUIApplication()
        app.launchEnvironment["SIFT_BACKEND_BASE_URL"] = "http://127.0.0.1:\(server.port)"
        app.launch()

        let captureInput = app.textFields["capture.input"]
        XCTAssertTrue(captureInput.waitForExistence(timeout: 5))
        captureInput.tap()
        captureInput.typeText("Resume after relaunch")
        app.buttons["capture.submit"].tap()
        XCTAssertTrue(server.waitForRequest(containing: "POST /v1/concept-runs", timeout: 5))

        app.terminate()
        server.setRunCompleted(true)
        app.launch()

        let recoveredTitle = app.staticTexts["Recovered After Relaunch"]
        XCTAssertTrue(recoveredTitle.waitForExistence(timeout: 10))
        XCTAssertEqual(
            app.staticTexts.matching(
                NSPredicate(format: "label == %@", "Recovered After Relaunch")
            ).count,
            1
        )
        XCTAssertEqual(server.requestCount(containing: "POST /v1/concept-runs"), 1)
        XCTAssertTrue(server.waitForRequest(containing: "GET /v1/model-runs?active=false", timeout: 5))
    }

    func testInitialModelRunCompletesInTheOpenedDraftConversation() throws {
        server.setRunCompleted(false)
        let app = XCUIApplication()
        app.launchEnvironment["SIFT_BACKEND_BASE_URL"] = "http://127.0.0.1:\(server.port)"
        app.launchEnvironment["SIFT_UI_TEST_IN_MEMORY"] = "1"
        app.launch()

        let captureInput = app.textFields["capture.input"]
        XCTAssertTrue(captureInput.waitForExistence(timeout: 5))
        captureInput.tap()
        captureInput.typeText("Stay in this conversation")
        app.buttons["capture.submit"].tap()
        XCTAssertTrue(server.waitForRequest(containing: "POST /v1/concept-runs", timeout: 5))

        server.setRunCompleted(true)

        XCTAssertTrue(
            app.staticTexts["Recovered After Relaunch"].waitForExistence(timeout: 10),
            app.debugDescription
        )
        XCTAssertTrue(app.staticTexts["A durable UI test answer."].waitForExistence(timeout: 5))
        XCTAssertEqual(server.requestCount(containing: "POST /v1/concept-runs"), 1)
    }

    func testFailedCardRetryMovesIntoConversationAndKeepsAnchorAfterCompletion() throws {
        server.beginFailedCardRetry()
        let app = XCUIApplication()
        app.launchEnvironment["SIFT_BACKEND_BASE_URL"] = "http://127.0.0.1:\(server.port)"
        app.launchEnvironment["SIFT_UI_TEST_IN_MEMORY"] = "1"
        app.launch()

        openConcept(named: "Retry this concept", in: app)
        let retry = app.buttons["Try again"]
        XCTAssertTrue(retry.waitForExistence(timeout: 5), app.debugDescription)
        retry.tap()

        XCTAssertTrue(
            app.staticTexts["Retry this concept"].waitForExistence(timeout: 5),
            app.debugDescription
        )
        XCTAssertTrue(app.staticTexts["A durable UI test answer."].waitForExistence(timeout: 10))
        XCTAssertTrue(app.buttons["Show concept card"].waitForExistence(timeout: 5))
        XCTAssertEqual(server.requestCount(containing: "POST /v1/concept-runs"), 1)
    }

    func testFollowUpModelRunCompletesAfterAppTerminationAndReloadsConversation() throws {
        server.beginFollowUpRecovery()
        let app = XCUIApplication()
        app.launchEnvironment["SIFT_BACKEND_BASE_URL"] = "http://127.0.0.1:\(server.port)"
        app.launch()

        openConcept(named: "UI Test Concept", in: app)
        let input = app.textFields["concept.composer.input"]
        XCTAssertTrue(input.waitForExistence(timeout: 5))
        input.tap()
        input.typeText("Follow-up survives relaunch")
        app.buttons["concept.composer.action"].tap()
        XCTAssertTrue(server.waitForRequest(containing: "/turn-runs", timeout: 5))

        app.terminate()
        server.setRunCompleted(true)
        app.launch()

        openConcept(named: "UI Test Concept", in: app)
        let showConversation = app.buttons["Show conversation"]
        if showConversation.waitForExistence(timeout: 2) {
            showConversation.tap()
        }
        let recoveredAnswer = app.staticTexts["Recovered follow-up answer."]
        XCTAssertTrue(recoveredAnswer.waitForExistence(timeout: 10))
        XCTAssertEqual(
            app.staticTexts.matching(
                NSPredicate(format: "label == %@", "Recovered follow-up answer.")
            ).count,
            1
        )
        XCTAssertEqual(
            app.staticTexts.matching(
                NSPredicate(format: "label == %@", "Follow-up survives relaunch")
            ).count,
            1
        )
        XCTAssertEqual(server.requestCount(containing: "/turn-runs"), 1)
        XCTAssertFalse(app.staticTexts["Previous follow-up was not sent. You can edit and retry it."].exists)
        XCTAssertTrue(server.waitForRequest(containing: "GET /v1/model-runs?active=false", timeout: 5))
    }

    func testManagedRunWaitingForCredentialResumesWithEphemeralProviderKey() throws {
        server.beginManagedCredentialResume()
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
        XCTAssertTrue(captureInput.waitForExistence(timeout: 5))
        captureInput.tap()
        captureInput.typeText("Resume with an ephemeral credential")
        app.buttons["capture.submit"].tap()

        XCTAssertTrue(
            server.waitForCredentialResume(timeout: 5),
            "Requests: \(server.receivedRequests)\nUI: \(app.debugDescription)"
        )
        XCTAssertFalse(server.resumeBodyContainedProviderKey)
        XCTAssertTrue(
            app.staticTexts["Credential Resume Concept"].waitForExistence(timeout: 10),
            "Requests: \(server.receivedRequests)\nUI: \(app.debugDescription)"
        )
    }

    func testPeriodicReviewAppearsWithoutReopeningConcept() throws {
        server.beginPeriodicReview()
        let app = XCUIApplication()
        app.launchEnvironment["SIFT_BACKEND_BASE_URL"] = "http://127.0.0.1:\(server.port)"
        app.launchEnvironment["SIFT_UI_TEST_IN_MEMORY"] = "1"
        app.launch()

        openConcept(named: "UI Test Concept", in: app)
        let input = app.textFields["concept.composer.input"]
        XCTAssertTrue(input.waitForExistence(timeout: 5))
        input.tap()
        input.typeText("Fifth follow-up triggers review")
        app.buttons["concept.composer.action"].tap()

        XCTAssertTrue(app.staticTexts["Periodic review follow-up answer."].waitForExistence(timeout: 10))
        let showCard = app.buttons["Show concept card"]
        if showCard.waitForExistence(timeout: 2) {
            showCard.tap()
        }
        XCTAssertTrue(
            app.staticTexts["Periodic review"].waitForExistence(timeout: 10),
            "Requests: \(server.receivedRequests)\nUI: \(app.debugDescription)"
        )
        XCTAssertTrue(server.waitForRequest(containing: "/proposals?status=proposed", timeout: 5))
    }

    func testVersionHistoryPreviewsAndRestoresAnOlderRevision() throws {
        server.beginVersionHistory()
        let app = XCUIApplication()
        app.launchEnvironment["SIFT_BACKEND_BASE_URL"] = "http://127.0.0.1:\(server.port)"
        app.launchEnvironment["SIFT_UI_TEST_IN_MEMORY"] = "1"
        app.launch()

        openConcept(named: "UI Test Concept", in: app)
        openVersionHistory(in: app)
        app.staticTexts["Version 1"].tap()
        XCTAssertTrue(
            server.waitForRequest(containing: "/revisions/1", timeout: 5),
            "Requests: \(server.receivedRequests)"
        )
        XCTAssertTrue(
            app.staticTexts["Historical explanation."].waitForExistence(timeout: 5),
            "Requests: \(server.receivedRequests)\nUI: \(app.debugDescription)"
        )

        let restore = app.buttons["concept.history.restore"]
        XCTAssertTrue(restore.waitForExistence(timeout: 5))
        let enabled = XCTNSPredicateExpectation(
            predicate: NSPredicate(format: "enabled == true"),
            object: restore
        )
        XCTAssertEqual(XCTWaiter.wait(for: [enabled], timeout: 5), .completed)
        restore.tap()
        app.alerts.buttons["Restore"].tap()
        XCTAssertTrue(server.waitForRequest(containing: "/revisions/1/restore", timeout: 5))
        XCTAssertTrue(app.navigationBars["Version history"].waitForExistence(timeout: 5))
    }

    func testVersionHistoryDisablesRestoreWhenBackendIsKnownUnavailable() throws {
        server.beginVersionHistory(backendUnavailable: true)
        let app = XCUIApplication()
        app.launchEnvironment["SIFT_BACKEND_BASE_URL"] = "http://127.0.0.1:\(server.port)"
        app.launchEnvironment["SIFT_UI_TEST_IN_MEMORY"] = "1"
        app.launch()

        XCTAssertTrue(server.waitForRequest(containing: "GET /v1/app-status", timeout: 5))
        openConcept(named: "UI Test Concept", in: app)
        openVersionHistory(in: app)
        app.staticTexts["Version 1"].tap()

        let restore = app.buttons["concept.history.restore"]
        XCTAssertTrue(
            restore.waitForExistence(timeout: 5),
            "Requests: \(server.receivedRequests)\nUI: \(app.debugDescription)"
        )
        XCTAssertTrue(app.staticTexts["concept.history.offline"].waitForExistence(timeout: 5))
        XCTAssertFalse(restore.isEnabled)
    }

    func testVersionHistoryShowsEmptyState() throws {
        server.beginVersionHistory(empty: true)
        let app = XCUIApplication()
        app.launchEnvironment["SIFT_BACKEND_BASE_URL"] = "http://127.0.0.1:\(server.port)"
        app.launchEnvironment["SIFT_UI_TEST_IN_MEMORY"] = "1"
        app.launch()

        openConcept(named: "UI Test Concept", in: app)
        openVersionHistory(in: app)
        XCTAssertTrue(app.staticTexts["No version history"].waitForExistence(timeout: 5))
    }

    private func openConcept(named title: String, in app: XCUIApplication) {
        app.buttons["Library"].tap()
        let concept = app.staticTexts[title]
        XCTAssertTrue(concept.waitForExistence(timeout: 5), app.debugDescription)
        concept.tap()
    }

    private func openVersionHistory(in app: XCUIApplication) {
        app.buttons["concept.actions"].tap()
        let history = app.buttons["concept.history.open"]
        XCTAssertTrue(history.waitForExistence(timeout: 2), app.debugDescription)
        history.tap()
        XCTAssertTrue(app.navigationBars["Version history"].waitForExistence(timeout: 5))
    }
}

private final class LocalHTTPServer: @unchecked Sendable {
    private let listener: NWListener
    private let queue = DispatchQueue(label: "app.sift.ui-test-http")
    private let lock = NSLock()
    private var connections: [NWConnection] = []
    private var requests: [String] = []
    private var runCompleted = true
    private var recoveryScenario = false
    private var followUpRecoveryScenario = false
    private var managedCredentialResumeScenario = false
    private var periodicReviewScenario = false
    private var versionHistoryScenario = false
    private var versionHistoryBackendUnavailable = false
    private var versionHistoryEmpty = false
    private var failedCardRetryScenario = false
    private var failedCardRetryCompleted = false
    private var reviewPollCount = 0
    private var credentialResumeReceived = false
    private var credentialResumeHadExpectedHeader = false
    private var credentialResumeBodyHadProviderKey = false
    private var runIdempotencyKey: String?
    private(set) var port: UInt16 = 0

    var receivedRequests: [String] {
        lock.lock()
        defer { lock.unlock() }
        return requests
    }

    func setRunCompleted(_ completed: Bool) {
        lock.lock()
        runCompleted = completed
        if !completed { recoveryScenario = true }
        lock.unlock()
    }

    func beginFollowUpRecovery() {
        lock.lock()
        runCompleted = false
        recoveryScenario = false
        followUpRecoveryScenario = true
        runIdempotencyKey = nil
        lock.unlock()
    }

    func beginManagedCredentialResume() {
        lock.lock()
        runCompleted = false
        recoveryScenario = false
        followUpRecoveryScenario = false
        managedCredentialResumeScenario = true
        credentialResumeReceived = false
        credentialResumeHadExpectedHeader = false
        credentialResumeBodyHadProviderKey = false
        runIdempotencyKey = nil
        lock.unlock()
    }

    func beginPeriodicReview() {
        lock.lock()
        runCompleted = true
        recoveryScenario = false
        followUpRecoveryScenario = false
        managedCredentialResumeScenario = false
        periodicReviewScenario = true
        reviewPollCount = 0
        runIdempotencyKey = nil
        lock.unlock()
    }

    func beginVersionHistory(backendUnavailable: Bool = false, empty: Bool = false) {
        lock.lock()
        runCompleted = true
        recoveryScenario = false
        followUpRecoveryScenario = false
        managedCredentialResumeScenario = false
        periodicReviewScenario = false
        versionHistoryScenario = true
        versionHistoryBackendUnavailable = backendUnavailable
        versionHistoryEmpty = empty
        runIdempotencyKey = nil
        lock.unlock()
    }

    func beginFailedCardRetry() {
        lock.lock()
        runCompleted = true
        recoveryScenario = false
        followUpRecoveryScenario = false
        managedCredentialResumeScenario = false
        periodicReviewScenario = false
        versionHistoryScenario = false
        failedCardRetryScenario = true
        failedCardRetryCompleted = false
        runIdempotencyKey = nil
        lock.unlock()
    }

    func waitForCredentialResume(timeout: TimeInterval) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            lock.lock()
            let completed = credentialResumeReceived && credentialResumeHadExpectedHeader
            lock.unlock()
            if completed { return true }
            Thread.sleep(forTimeInterval: 0.05)
        }
        return false
    }

    var resumeBodyContainedProviderKey: Bool {
        lock.lock()
        defer { lock.unlock() }
        return credentialResumeBodyHadProviderKey
    }

    func waitForRequest(containing fragment: String, timeout: TimeInterval) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if receivedRequests.contains(where: { $0.contains(fragment) }) { return true }
            Thread.sleep(forTimeInterval: 0.05)
        }
        return false
    }

    func requestCount(containing fragment: String) -> Int {
        receivedRequests.count { $0.contains(fragment) }
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
        if method == "POST", path == "/v1/concept-runs" || path.hasSuffix("/turn-runs") {
            runIdempotencyKey = request
                .components(separatedBy: "\r\n")
                .first { $0.lowercased().hasPrefix("idempotency-key:") }
                .map { String($0.split(separator: ":", maxSplits: 1)[1]).trimmingCharacters(in: .whitespaces) }
            if failedCardRetryScenario {
                failedCardRetryCompleted = true
            }
        }
        if method == "POST", path.hasSuffix("/resume") || path.hasSuffix("/resume-stream") {
            let providerKey = request
                .components(separatedBy: "\r\n")
                .first { $0.lowercased().hasPrefix("x-sift-provider-key:") }
                .map { String($0.split(separator: ":", maxSplits: 1)[1]).trimmingCharacters(in: .whitespaces) }
            let body = request.components(separatedBy: "\r\n\r\n").dropFirst().joined()
            credentialResumeReceived = true
            credentialResumeHadExpectedHeader = providerKey == "sk-ui-test-secret"
            credentialResumeBodyHadProviderKey = body.contains("sk-ui-test-secret")
            runCompleted = true
        }
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
            if isVersionHistoryBackendUnavailable {
                return HTTPResponse(
                    status: "503 Service Unavailable",
                    contentType: "application/json",
                    body: "{\"detail\":\"unavailable\"}"
                )
            }
            return .json("""
            {"env":"ui-test","modelProvider":"openai","explainModel":"gpt-ui-test","webSearchEnabled":true,"databaseURL":"managed","providerBaseURL":"https://api.openai.com/v1","apiKeyConfigured":true}
            """)
        }
        if method == "GET", path == "/v1/concepts" {
            return .json(runIsCompleted || isFollowUpRecovery ? "[\(conceptJSON)]" : "[]")
        }
        if method == "POST", path == "/v1/concept-runs" {
            return .json(modelRunJSON)
        }
        if method == "POST", path.hasSuffix("/turn-runs") {
            return .json(modelRunJSON)
        }
        if method == "GET", path.hasPrefix("/v1/model-runs?active=") {
            return .json(runIdempotencyKey == nil ? "[]" : "[\(modelRunJSON)]")
        }
        if method == "GET", path.contains("/events") {
            return .json("[]")
        }
        if method == "GET", isPeriodicReview, path.contains("00000000-0000-0000-0000-000000000302") {
            return .json(periodicSummaryRunJSON)
        }
        if method == "GET", isPeriodicReview, path.contains("00000000-0000-0000-0000-000000000303") {
            return .json(periodicReviewRunJSON)
        }
        if method == "GET", path.hasPrefix("/v1/model-runs/") {
            return .json(modelRunJSON)
        }
        if method == "POST", isPeriodicReview,
           path.contains("00000000-0000-0000-0000-000000000303"),
           path.hasSuffix("/resume") {
            return .json(periodicReviewRunJSON)
        }
        if method == "POST", path.hasPrefix("/v1/model-runs/"), path.hasSuffix("/resume") {
            return .json(modelRunJSON)
        }
        if method == "POST", path.hasPrefix("/v1/model-runs/"), path.hasSuffix("/resume-stream") {
            let body = [
                "{\"type\":\"progress\",\"progressLabel\":\"Writing first answer\",\"sequence\":2}",
                "{\"type\":\"delta\",\"delta\":\"A durable \"}",
                "{\"type\":\"delta\",\"delta\":\"UI test answer.\"}",
                "{\"type\":\"completed\",\"modelRun\":\(modelRunJSON)}",
            ].joined(separator: "\n") + "\n"
            return HTTPResponse(
                status: "200 OK",
                contentType: "application/x-ndjson",
                body: body
            )
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
            return .json(conceptTurnsJSON)
        }
        if method == "GET", isVersionHistory, path.hasSuffix("/revisions") {
            return .json(isVersionHistoryEmpty ? "[]" : revisionSummariesJSON)
        }
        if method == "GET", isVersionHistory, path.hasSuffix("/revisions/1") {
            return .json(revisionDetailJSON)
        }
        if method == "POST", isVersionHistory, path.hasSuffix("/revisions/1/restore") {
            return .json(conceptJSON)
        }
        if method == "GET", path.contains("/proposals?status=proposed") {
            return .json(isPeriodicReviewReady ? "[\(periodicProposalJSON)]" : "[]")
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
        let title = if isRecoveryScenario {
            "Recovered After Relaunch"
        } else if isManagedCredentialResume {
            "Credential Resume Concept"
        } else {
            "UI Test Concept"
        }
        let isFailedRetry = isFailedCardRetryPending
        let displayTitle = isFailedRetry ? "Retry this concept" : title
        let explanation = isFailedRetry ? "" : "Generated through the managed beta UI journey."
        let initialAnswer = isFailedRetry ? "" : "A durable UI test answer."
        let status = isFailedRetry ? "generationFailed" : "ready"
        return """
        {"id":"00000000-0000-0000-0000-000000000101","canonicalTitle":"ui-test-concept","displayTitle":"\(displayTitle)","oneLineExplanation":"\(explanation)","initialAnswer":"\(initialAnswer)","maturity":"initial","captureStatus":"\(status)","noteRevision":1,"blocks":[],"tags":[],"topics":[],"relations":[]}
        """
    }

    private var modelRunJSON: String {
        let key = runIdempotencyKey ?? "ui-test-run"
        if isPeriodicReview {
            return """
            {"id":"00000000-0000-0000-0000-000000000301","kind":"followUp","status":"succeeded","conceptId":"00000000-0000-0000-0000-000000000101","idempotencyKey":"\(key)","providerSnapshot":{},"checkpoint":"modelCompleted","result":{"response":\(followUpResponseJSON)},"childRunIds":["00000000-0000-0000-0000-000000000302","00000000-0000-0000-0000-000000000303"],"createdAt":"2033-01-01T00:00:00Z","updatedAt":"2033-01-01T00:00:00Z"}
            """
        }
        if isManagedCredentialResume {
            if !runIsCompleted {
                return """
                {"id":"00000000-0000-0000-0000-000000000203","kind":"initialConcept","status":"waitingForCredential","clientDraftId":"\(key)","idempotencyKey":"\(key)","providerSnapshot":{},"errorCode":"credential_required","errorMessage":"Reconnect to resume this model run.","childRunIds":[],"createdAt":"2033-01-01T00:00:00Z","updatedAt":"2033-01-01T00:00:00Z"}
                """
            }
            return """
            {"id":"00000000-0000-0000-0000-000000000203","kind":"initialConcept","status":"succeeded","conceptId":"00000000-0000-0000-0000-000000000101","clientDraftId":"\(key)","idempotencyKey":"\(key)","providerSnapshot":{},"checkpoint":"modelCompleted","result":{"concept":\(conceptJSON)},"childRunIds":[],"createdAt":"2033-01-01T00:00:00Z","updatedAt":"2033-01-01T00:00:00Z"}
            """
        }
        if isFollowUpRecovery {
            if !runIsCompleted {
                return """
                {"id":"00000000-0000-0000-0000-000000000202","kind":"followUp","status":"running","conceptId":"00000000-0000-0000-0000-000000000101","idempotencyKey":"\(key)","providerSnapshot":{},"childRunIds":[],"createdAt":"2033-01-01T00:00:00Z","updatedAt":"2033-01-01T00:00:00Z"}
                """
            }
            return """
            {"id":"00000000-0000-0000-0000-000000000202","kind":"followUp","status":"succeeded","conceptId":"00000000-0000-0000-0000-000000000101","idempotencyKey":"\(key)","providerSnapshot":{},"checkpoint":"modelCompleted","result":{"response":\(followUpResponseJSON)},"childRunIds":[],"createdAt":"2033-01-01T00:00:00Z","updatedAt":"2033-01-01T00:00:00Z"}
            """
        }
        if !runIsCompleted {
            return """
            {"id":"00000000-0000-0000-0000-000000000201","kind":"initialConcept","status":"running","clientDraftId":"\(key)","idempotencyKey":"\(key)","providerSnapshot":{},"childRunIds":[],"createdAt":"2033-01-01T00:00:00Z","updatedAt":"2033-01-01T00:00:00Z"}
            """
        }
        return """
        {"id":"00000000-0000-0000-0000-000000000201","kind":"initialConcept","status":"succeeded","conceptId":"00000000-0000-0000-0000-000000000101","clientDraftId":"\(key)","idempotencyKey":"\(key)","providerSnapshot":{},"checkpoint":"modelCompleted","result":{"concept":\(conceptJSON)},"childRunIds":[],"createdAt":"2033-01-01T00:00:00Z","updatedAt":"2033-01-01T00:00:00Z"}
        """
    }

    private var followUpResponseJSON: String {
        let answer = isPeriodicReview
            ? "Periodic review follow-up answer."
            : "Recovered follow-up answer."
        return """
        {"answer":"\(answer)","answerSource":{"sourceType":"modelKnowledge","confidence":0.8,"retrievalUsed":false,"citations":[]},"updateMode":"none","concept":\(conceptJSON),"proposal":null}
        """
    }

    private var periodicSummaryRunJSON: String {
        """
        {"id":"00000000-0000-0000-0000-000000000302","kind":"continuitySummary","status":"succeeded","conceptId":"00000000-0000-0000-0000-000000000101","idempotencyKey":"summary","providerSnapshot":{},"checkpoint":"modelCompleted","childRunIds":[],"createdAt":"2033-01-01T00:00:00Z","updatedAt":"2033-01-01T00:00:00Z"}
        """
    }

    private var periodicReviewRunJSON: String {
        lock.lock()
        reviewPollCount += 1
        let completed = reviewPollCount >= 2
        lock.unlock()
        return """
        {"id":"00000000-0000-0000-0000-000000000303","kind":"knowledgeReview","status":"\(completed ? "succeeded" : "running")","conceptId":"00000000-0000-0000-0000-000000000101","idempotencyKey":"review","providerSnapshot":{},"checkpoint":"\(completed ? "modelCompleted" : "")","childRunIds":[],"createdAt":"2033-01-01T00:00:00Z","updatedAt":"2033-01-01T00:00:00Z"}
        """
    }

    private var periodicProposalJSON: String {
        """
        {"id":"00000000-0000-0000-0000-000000000304","baseNoteRevision":1,"patchOperations":[],"rationale":"Keep the card aligned with the latest discussion.","confidence":0.8,"status":"proposed","origin":"periodicReview","sourceRunId":"00000000-0000-0000-0000-000000000303"}
        """
    }

    private var revisionSummariesJSON: String {
        """
        [{"revision":1,"source":"initialGeneration","createdAt":"2033-01-01T00:00:00Z","isCurrent":false,"restoredFromRevision":null},{"revision":2,"source":"manualEdit","createdAt":"2033-01-02T00:00:00Z","isCurrent":true,"restoredFromRevision":null}]
        """
    }

    private var revisionDetailJSON: String {
        """
        {"revision":1,"source":"initialGeneration","createdAt":"2033-01-01T00:00:00Z","isCurrent":false,"restoredFromRevision":null,"snapshotSchemaVersion":2,"displayTitle":"Historical UI Test Concept","canonicalTitle":"historical-ui-test-concept","oneLineExplanation":"Historical explanation.","blocks":[{"id":"00000000-0000-0000-0000-000000000401","blockType":"whatItIs","content":"Historical block content.","position":0,"source":"ai","isUserLocked":false}]}
        """
    }

    private var conceptTurnsJSON: String {
        guard isFollowUpRecovery, runIsCompleted else { return "[]" }
        return """
        [{"role":"user","content":"UI Test Concept","status":"completed"},{"role":"assistant","content":"A durable UI test answer.","status":"completed"},{"role":"user","content":"Follow-up survives relaunch","status":"completed"},{"role":"assistant","content":"Recovered follow-up answer.","status":"completed"}]
        """
    }

    private var runIsCompleted: Bool {
        lock.lock()
        defer { lock.unlock() }
        return runCompleted
    }

    private var isRecoveryScenario: Bool {
        lock.lock()
        defer { lock.unlock() }
        return recoveryScenario
    }

    private var isFollowUpRecovery: Bool {
        lock.lock()
        defer { lock.unlock() }
        return followUpRecoveryScenario
    }

    private var isManagedCredentialResume: Bool {
        lock.lock()
        defer { lock.unlock() }
        return managedCredentialResumeScenario
    }

    private var isPeriodicReview: Bool {
        lock.lock()
        defer { lock.unlock() }
        return periodicReviewScenario
    }

    private var isPeriodicReviewReady: Bool {
        lock.lock()
        defer { lock.unlock() }
        return periodicReviewScenario && reviewPollCount >= 2
    }

    private var isVersionHistory: Bool {
        lock.lock()
        defer { lock.unlock() }
        return versionHistoryScenario
    }

    private var isVersionHistoryBackendUnavailable: Bool {
        lock.lock()
        defer { lock.unlock() }
        return versionHistoryScenario && versionHistoryBackendUnavailable
    }

    private var isVersionHistoryEmpty: Bool {
        lock.lock()
        defer { lock.unlock() }
        return versionHistoryScenario && versionHistoryEmpty
    }

    private var isFailedCardRetryPending: Bool {
        lock.lock()
        defer { lock.unlock() }
        return failedCardRetryScenario && !failedCardRetryCompleted
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
