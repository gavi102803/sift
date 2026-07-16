import Foundation

protocol SiftAPIClient {
    var backendDescription: String { get }
    var requiresBetaActivation: Bool { get }
    var hasBetaSession: Bool { get }

    func activateBeta(inviteCode: String) async throws
    func clearBetaSession()

    func getAppStatus() async throws -> AppStatusDTO
    func getModelProviderSettings() async throws -> ModelProviderSettingsDTO
    func listRuntimeModelProviders() async throws -> RuntimeProviderCatalogDTO
    func listRuntimeWebProviders() async throws -> WebProviderCatalogDTO
    func updateModelProviderSettings(
        _ request: UpdateModelProviderSettingsRequest
    ) async throws -> ModelProviderSettingsDTO
    func getWebProviderSettings() async throws -> WebProviderSettingsDTO
    func updateWebProviderSettings(
        _ request: UpdateWebProviderSettingsRequest
    ) async throws -> WebProviderSettingsDTO
    func listProviderModels() async throws -> ProviderModelListDTO
    func runModelDiagnostic() async throws -> ModelDiagnosticDTO
    func runWebSearchDiagnostic() async throws -> ModelDiagnosticDTO
    func listConcepts() async throws -> [ConceptDTO]
    func getConcept(id: UUID) async throws -> ConceptDTO
    func updateConceptSummary(id: UUID, request: UpdateConceptSummaryRequest) async throws -> ConceptDTO
    func updateNoteBlock(
        conceptId: UUID,
        blockId: UUID,
        request: UpdateNoteBlockRequest
    ) async throws -> ConceptDTO
    func updateConceptNote(
        id: UUID,
        request: UpdateConceptNoteRequest
    ) async throws -> ConceptDTO
    func updateConceptOrganization(
        id: UUID,
        request: UpdateConceptOrganizationRequest
    ) async throws -> ConceptDTO
    func addRelation(conceptId: UUID, request: CreateConceptRelationRequest) async throws -> ConceptDTO
    func removeRelation(conceptId: UUID, relationId: UUID) async throws -> ConceptDTO
    func listTurns(conceptId: UUID) async throws -> [ConceptHistoryTurnDTO]
    func createConcept(_ request: CreateConceptRequest) async throws -> ConceptDTO
    func createConcept(
        _ request: CreateConceptRequest,
        idempotencyKey: UUID?
    ) async throws -> ConceptDTO
    func streamCreateConcept(
        _ request: CreateConceptRequest,
        idempotencyKey: UUID?
    ) -> AsyncThrowingStream<ConceptInitialStreamEvent, Error>
    func submitTurn(conceptId: UUID, request: ConceptTurnRequest) async throws -> ConceptTurnResponse
    func submitTurn(
        conceptId: UUID,
        request: ConceptTurnRequest,
        idempotencyKey: UUID?
    ) async throws -> ConceptTurnResponse
    func streamTurn(
        conceptId: UUID,
        request: ConceptTurnRequest
    ) -> AsyncThrowingStream<ConceptTurnStreamEvent, Error>
    func streamTurn(
        conceptId: UUID,
        request: ConceptTurnRequest,
        idempotencyKey: UUID?
    ) -> AsyncThrowingStream<ConceptTurnStreamEvent, Error>
    func mergeProposal(id: UUID) async throws -> ConceptDTO
    func mergeProposal(id: UUID, idempotencyKey: UUID?) async throws -> ConceptDTO
    func dismissProposal(id: UUID) async throws
}

extension SiftAPIClient {
    var requiresBetaActivation: Bool { false }
    var hasBetaSession: Bool { true }

    func activateBeta(inviteCode: String) async throws {}
    func clearBetaSession() {}

    func createConcept(
        _ request: CreateConceptRequest,
        idempotencyKey: UUID?
    ) async throws -> ConceptDTO {
        try await createConcept(request)
    }

    func submitTurn(
        conceptId: UUID,
        request: ConceptTurnRequest,
        idempotencyKey: UUID?
    ) async throws -> ConceptTurnResponse {
        try await submitTurn(conceptId: conceptId, request: request)
    }

    func streamTurn(
        conceptId: UUID,
        request: ConceptTurnRequest,
        idempotencyKey: UUID?
    ) -> AsyncThrowingStream<ConceptTurnStreamEvent, Error> {
        streamTurn(conceptId: conceptId, request: request)
    }

    func streamCreateConcept(
        _ request: CreateConceptRequest,
        idempotencyKey: UUID?
    ) -> AsyncThrowingStream<ConceptInitialStreamEvent, Error> {
        AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    let concept = try await createConcept(request, idempotencyKey: idempotencyKey)
                    continuation.yield(ConceptInitialStreamEvent(type: "started", delta: nil, concept: nil))
                    let answer = concept.initialAnswer ?? concept.oneLineExplanation
                    for chunk in answer.siftChunks(maxLength: 16) {
                        try await Task.sleep(nanoseconds: 45_000_000)
                        continuation.yield(ConceptInitialStreamEvent(type: "delta", delta: chunk, concept: nil))
                    }
                    continuation.yield(ConceptInitialStreamEvent(type: "completed", delta: nil, concept: concept))
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { @Sendable _ in task.cancel() }
        }
    }

    func mergeProposal(id: UUID, idempotencyKey: UUID?) async throws -> ConceptDTO {
        try await mergeProposal(id: id)
    }
}

enum SiftAPIClientFactory {
#if DEBUG
    private static let uiTestCredentialStore = InMemoryManagedCredentialStore(
        installationId: "sift-ui-test-installation"
    )
#endif

    /// The live client resolves its base URL per request via
    /// `BackendEndpointResolver`, so a saved Personal URL applies immediately.
    /// Mock is intentionally **not** a silent fallback here — it is only used for
    /// previews/tests via `AppServices.preview`, so a real backend being down is
    /// reported as "unavailable", never disguised as mock data.
    static func makeDefault() -> any SiftAPIClient {
#if DEBUG
        if ProcessInfo.processInfo.environment["SIFT_UI_TEST_IN_MEMORY_CREDENTIALS"] == "1" {
            return HTTPSiftAPIClient(credentialStore: uiTestCredentialStore)
        }
#endif
        return HTTPSiftAPIClient()
    }
}

struct HTTPSiftAPIClient: SiftAPIClient {
    /// When non-nil the base URL is fixed (tests / explicit callers). When nil it
    /// is resolved per request from `BackendEndpointResolver`, so a freshly-saved
    /// Personal backend URL takes effect immediately without an app restart.
    private let fixedBaseURL: URL?
    private let credentialStore: any ManagedCredentialStore
    private let sessionController: ManagedSessionController
    private let managedModeOverride: Bool?
    var urlSession: URLSession = .shared
    var jsonDecoder: JSONDecoder = JSONDecoder()
    var jsonEncoder: JSONEncoder = JSONEncoder()

    init(
        baseURL: URL? = nil,
        urlSession: URLSession = .shared,
        credentialStore: any ManagedCredentialStore = KeychainManagedCredentialStore.shared,
        managedMode: Bool? = nil
    ) {
        self.fixedBaseURL = baseURL
        self.urlSession = urlSession
        self.credentialStore = credentialStore
        self.sessionController = ManagedSessionController(credentialStore: credentialStore)
        self.managedModeOverride = managedMode
        self.jsonDecoder.dateDecodingStrategy = .iso8601
        self.jsonEncoder.dateEncodingStrategy = .iso8601
    }

    var baseURL: URL {
        fixedBaseURL ?? BackendEndpointResolver.current()
    }

    var backendDescription: String {
        baseURL.absoluteString
    }

    var requiresBetaActivation: Bool {
        managedModeOverride ?? ManagedBuild.isEnabled
    }

    var hasBetaSession: Bool {
        credentialStore.betaSession.map { $0.expiresAt > Date() } ?? false
    }

    func activateBeta(inviteCode: String) async throws {
        let response: BetaSessionDTO = try await post(
            path: "/v1/beta/activate",
            body: ActivateBetaRequest(
                inviteCode: inviteCode,
                installationId: credentialStore.installationId
            ),
            authorized: false
        )
        credentialStore.betaSession = ManagedBetaSession(
            betaAccessToken: response.betaAccessToken,
            ownerId: response.ownerId,
            expiresAt: response.expiresAt
        )
    }

    func clearBetaSession() {
        credentialStore.clearBetaSession()
    }

    func getAppStatus() async throws -> AppStatusDTO {
        try await get(path: "/v1/app-status")
    }

    func getModelProviderSettings() async throws -> ModelProviderSettingsDTO {
        if requiresBetaActivation {
            let connection: ManagedProviderConnectionDTO = try await get(
                path: "/v1/provider-connection"
            )
            return managedSettings(from: connection)
        }
        return try await get(path: "/v1/model-provider-settings")
    }

    func listRuntimeModelProviders() async throws -> RuntimeProviderCatalogDTO {
        try await get(path: "/v1/runtime/model-providers")
    }

    func listRuntimeWebProviders() async throws -> WebProviderCatalogDTO {
        try await get(path: "/v1/runtime/web-providers")
    }

    func updateModelProviderSettings(
        _ request: UpdateModelProviderSettingsRequest
    ) async throws -> ModelProviderSettingsDTO {
        if requiresBetaActivation {
            if let apiKey = request.apiKey, !apiKey.isEmpty {
                credentialStore.providerKey = apiKey
            }
            let managedRequest = ManagedProviderConnectionRequest(
                providerId: request.providerType,
                baseURL: request.baseURL,
                model: request.explainModel
            )
            let _: ManagedProviderTestDTO = try await post(
                path: "/v1/providers/test",
                body: managedRequest,
                includesProviderKey: true
            )
            let connection: ManagedProviderConnectionDTO = try await put(
                path: "/v1/provider-connection",
                body: managedRequest
            )
            return managedSettings(from: connection)
        }
        return try await put(path: "/v1/model-provider-settings", body: request)
    }

    func getWebProviderSettings() async throws -> WebProviderSettingsDTO {
        if requiresBetaActivation {
            return WebProviderSettingsDTO(
                providerType: "ddgs",
                apiKeyConfigured: false,
                apiKeyPreview: nil,
                webSearchEnabled: true
            )
        }
        return try await get(path: "/v1/web-provider-settings")
    }

    func updateWebProviderSettings(
        _ request: UpdateWebProviderSettingsRequest
    ) async throws -> WebProviderSettingsDTO {
        if requiresBetaActivation {
            guard request.providerType == "ddgs", request.apiKey?.isEmpty != false else {
                throw SiftAPIError.managedUnsupported
            }
            return WebProviderSettingsDTO(
                providerType: "ddgs",
                apiKeyConfigured: false,
                apiKeyPreview: nil,
                webSearchEnabled: request.webSearchEnabled
            )
        }
        return try await put(path: "/v1/web-provider-settings", body: request)
    }

    func listProviderModels() async throws -> ProviderModelListDTO {
        if requiresBetaActivation {
            let connection: ManagedProviderConnectionDTO = try await get(
                path: "/v1/provider-connection"
            )
            return ProviderModelListDTO(
                models: [ProviderModelDTO(id: connection.model, ownedBy: connection.providerId)]
            )
        }
        return try await get(path: "/v1/model-provider-settings/models")
    }

    func runModelDiagnostic() async throws -> ModelDiagnosticDTO {
        if requiresBetaActivation {
            let connection: ManagedProviderConnectionDTO = try await get(
                path: "/v1/provider-connection"
            )
            let result: ManagedProviderTestDTO = try await post(
                path: "/v1/providers/test",
                body: ManagedProviderConnectionRequest(
                    providerId: connection.providerId,
                    baseURL: connection.baseURL,
                    model: connection.model
                ),
                includesProviderKey: true
            )
            return ModelDiagnosticDTO(
                ok: result.ok,
                provider: connection.providerId,
                model: connection.model,
                message: result.ok ? "Provider connection is ready." : "Provider test failed.",
                webSearchUsed: nil,
                citationCount: nil
            )
        }
        return try await post(path: "/v1/model-diagnostic", body: EmptyRequest())
    }

    func runWebSearchDiagnostic() async throws -> ModelDiagnosticDTO {
        if requiresBetaActivation {
            return ModelDiagnosticDTO(
                ok: true,
                provider: "ddgs",
                model: "managed",
                message: "Managed beta web search is ready.",
                webSearchUsed: false,
                citationCount: 0
            )
        }
        return try await post(path: "/v1/web-search-diagnostic", body: EmptyRequest())
    }

    func listConcepts() async throws -> [ConceptDTO] {
        try await get(path: "/v1/concepts")
    }

    func getConcept(id: UUID) async throws -> ConceptDTO {
        try await get(path: "/v1/concepts/\(id.uuidString)")
    }

    func updateConceptSummary(id: UUID, request: UpdateConceptSummaryRequest) async throws -> ConceptDTO {
        try await patch(path: "/v1/concepts/\(id.uuidString)", body: request)
    }

    func updateNoteBlock(
        conceptId: UUID,
        blockId: UUID,
        request: UpdateNoteBlockRequest
    ) async throws -> ConceptDTO {
        try await patch(
            path: "/v1/concepts/\(conceptId.uuidString)/blocks/\(blockId.uuidString)",
            body: request
        )
    }

    func updateConceptNote(
        id: UUID,
        request: UpdateConceptNoteRequest
    ) async throws -> ConceptDTO {
        try await put(path: "/v1/concepts/\(id.uuidString)/note", body: request)
    }

    func updateConceptOrganization(
        id: UUID,
        request: UpdateConceptOrganizationRequest
    ) async throws -> ConceptDTO {
        try await patch(path: "/v1/concepts/\(id.uuidString)/organization", body: request)
    }

    func addRelation(conceptId: UUID, request: CreateConceptRelationRequest) async throws -> ConceptDTO {
        try await post(path: "/v1/concepts/\(conceptId.uuidString)/relations", body: request)
    }

    func removeRelation(conceptId: UUID, relationId: UUID) async throws -> ConceptDTO {
        try await delete(path: "/v1/concepts/\(conceptId.uuidString)/relations/\(relationId.uuidString)")
    }

    func listTurns(conceptId: UUID) async throws -> [ConceptHistoryTurnDTO] {
        try await get(path: "/v1/concepts/\(conceptId.uuidString)/turns")
    }

    func createConcept(_ request: CreateConceptRequest) async throws -> ConceptDTO {
        try await createConcept(request, idempotencyKey: nil)
    }

    func createConcept(
        _ request: CreateConceptRequest,
        idempotencyKey: UUID?
    ) async throws -> ConceptDTO {
        try await post(
            path: "/v1/concepts",
            body: request,
            idempotencyKey: idempotencyKey,
            includesProviderKey: requiresBetaActivation
        )
    }

    func streamCreateConcept(
        _ request: CreateConceptRequest,
        idempotencyKey: UUID?
    ) -> AsyncThrowingStream<ConceptInitialStreamEvent, Error> {
        AsyncThrowingStream { continuation in
            Task {
                do {
                    try await streamPost(
                        path: "/v1/concepts/stream",
                        body: request,
                        idempotencyKey: idempotencyKey,
                        includesProviderKey: requiresBetaActivation,
                        continuation: continuation
                    )
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
        }
    }

    func submitTurn(conceptId: UUID, request: ConceptTurnRequest) async throws -> ConceptTurnResponse {
        try await submitTurn(conceptId: conceptId, request: request, idempotencyKey: nil)
    }

    func submitTurn(
        conceptId: UUID,
        request: ConceptTurnRequest,
        idempotencyKey: UUID?
    ) async throws -> ConceptTurnResponse {
        try await post(
            path: "/v1/concepts/\(conceptId.uuidString)/turns",
            body: request,
            idempotencyKey: idempotencyKey,
            includesProviderKey: requiresBetaActivation
        )
    }

    func streamTurn(
        conceptId: UUID,
        request: ConceptTurnRequest
    ) -> AsyncThrowingStream<ConceptTurnStreamEvent, Error> {
        streamTurn(conceptId: conceptId, request: request, idempotencyKey: nil)
    }

    func streamTurn(
        conceptId: UUID,
        request: ConceptTurnRequest,
        idempotencyKey: UUID?
    ) -> AsyncThrowingStream<ConceptTurnStreamEvent, Error> {
        AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    try await streamPost(
                        path: "/v1/concepts/\(conceptId.uuidString)/turns/stream",
                        body: request,
                        idempotencyKey: idempotencyKey,
                        includesProviderKey: requiresBetaActivation,
                        continuation: continuation
                    )
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { @Sendable _ in task.cancel() }
        }
    }

    func mergeProposal(id: UUID) async throws -> ConceptDTO {
        try await mergeProposal(id: id, idempotencyKey: nil)
    }

    func mergeProposal(id: UUID, idempotencyKey: UUID?) async throws -> ConceptDTO {
        try await post(
            path: "/v1/update-proposals/\(id.uuidString)/merge",
            body: EmptyRequest(),
            idempotencyKey: idempotencyKey
        )
    }

    func dismissProposal(id: UUID) async throws {
        let _: EmptyResponse = try await post(
            path: "/v1/update-proposals/\(id.uuidString)/dismiss",
            body: EmptyRequest()
        )
    }

    private func get<Response: Decodable>(path: String) async throws -> Response {
        var urlRequest = URLRequest(url: baseURL.appending(path: path))
        try await authorize(&urlRequest)
        let (data, response) = try await urlSession.data(for: urlRequest)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw SiftAPIError.invalidResponse
        }
        guard (200..<300).contains(httpResponse.statusCode) else {
            throw await responseError(status: httpResponse.statusCode, data: data)
        }
        return try jsonDecoder.decode(Response.self, from: data)
    }

    private func post<Request: Encodable, Response: Decodable>(
        path: String,
        body: Request,
        idempotencyKey: UUID? = nil,
        authorized: Bool = true,
        includesProviderKey: Bool = false
    ) async throws -> Response {
        var urlRequest = URLRequest(url: baseURL.appending(path: path))
        urlRequest.httpMethod = "POST"
        urlRequest.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let idempotencyKey {
            urlRequest.setValue(idempotencyKey.uuidString, forHTTPHeaderField: "Idempotency-Key")
        }
        if authorized {
            try await authorize(&urlRequest, includesProviderKey: includesProviderKey)
        }
        urlRequest.httpBody = try jsonEncoder.encode(body)

        let (data, response) = try await urlSession.data(for: urlRequest)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw SiftAPIError.invalidResponse
        }
        guard (200..<300).contains(httpResponse.statusCode) else {
            throw await responseError(status: httpResponse.statusCode, data: data)
        }
        if Response.self == EmptyResponse.self {
            return EmptyResponse() as! Response
        }
        return try jsonDecoder.decode(Response.self, from: data)
    }

    private func streamPost<Request: Encodable, Event: Decodable>(
        path: String,
        body: Request,
        idempotencyKey: UUID? = nil,
        includesProviderKey: Bool = false,
        continuation: AsyncThrowingStream<Event, Error>.Continuation
    ) async throws {
        var urlRequest = URLRequest(url: baseURL.appending(path: path))
        urlRequest.httpMethod = "POST"
        urlRequest.setValue("application/json", forHTTPHeaderField: "Content-Type")
        urlRequest.setValue("application/x-ndjson", forHTTPHeaderField: "Accept")
        if let idempotencyKey {
            urlRequest.setValue(idempotencyKey.uuidString, forHTTPHeaderField: "Idempotency-Key")
        }
        try await authorize(&urlRequest, includesProviderKey: includesProviderKey)
        urlRequest.httpBody = try jsonEncoder.encode(body)

        let (bytes, response) = try await urlSession.bytes(for: urlRequest)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw SiftAPIError.invalidResponse
        }
        guard (200..<300).contains(httpResponse.statusCode) else {
            var data = Data()
            for try await byte in bytes {
                data.append(byte)
            }
            throw await responseError(status: httpResponse.statusCode, data: data)
        }

        for try await line in bytes.lines {
            try Task.checkCancellation()
            guard !line.isEmpty, let data = line.data(using: .utf8) else { continue }
            continuation.yield(try jsonDecoder.decode(Event.self, from: data))
        }
    }

    private func patch<Request: Encodable, Response: Decodable>(
        path: String,
        body: Request
    ) async throws -> Response {
        var urlRequest = URLRequest(url: baseURL.appending(path: path))
        urlRequest.httpMethod = "PATCH"
        urlRequest.setValue("application/json", forHTTPHeaderField: "Content-Type")
        urlRequest.httpBody = try jsonEncoder.encode(body)
        try await authorize(&urlRequest)

        let (data, response) = try await urlSession.data(for: urlRequest)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw SiftAPIError.invalidResponse
        }
        guard (200..<300).contains(httpResponse.statusCode) else {
            throw await responseError(status: httpResponse.statusCode, data: data)
        }
        return try jsonDecoder.decode(Response.self, from: data)
    }

    private func put<Request: Encodable, Response: Decodable>(
        path: String,
        body: Request
    ) async throws -> Response {
        var urlRequest = URLRequest(url: baseURL.appending(path: path))
        urlRequest.httpMethod = "PUT"
        urlRequest.setValue("application/json", forHTTPHeaderField: "Content-Type")
        urlRequest.httpBody = try jsonEncoder.encode(body)
        try await authorize(&urlRequest)

        let (data, response) = try await urlSession.data(for: urlRequest)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw SiftAPIError.invalidResponse
        }
        guard (200..<300).contains(httpResponse.statusCode) else {
            throw await responseError(status: httpResponse.statusCode, data: data)
        }
        return try jsonDecoder.decode(Response.self, from: data)
    }

    private func delete<Response: Decodable>(path: String) async throws -> Response {
        var urlRequest = URLRequest(url: baseURL.appending(path: path))
        urlRequest.httpMethod = "DELETE"
        try await authorize(&urlRequest)

        let (data, response) = try await urlSession.data(for: urlRequest)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw SiftAPIError.invalidResponse
        }
        guard (200..<300).contains(httpResponse.statusCode) else {
            throw await responseError(status: httpResponse.statusCode, data: data)
        }
        return try jsonDecoder.decode(Response.self, from: data)
    }

    private func errorDetail(from data: Data) -> SiftAPIErrorDetail? {
        try? jsonDecoder.decode(SiftAPIErrorEnvelope.self, from: data).resolvedDetail
    }

    private func responseError(status: Int, data: Data) async -> SiftAPIError {
        let detail = errorDetail(from: data)
        if status == 401,
           ["authentication_required", "beta_token_expired", "beta_token_revoked"].contains(detail?.code) {
            await sessionController.clearSession()
        }
        return .httpStatus(status, detail: detail)
    }

    private func authorize(
        _ request: inout URLRequest,
        includesProviderKey: Bool = false
    ) async throws {
        guard requiresBetaActivation else { return }
        let session = try await sessionController.sessionForRequest(
            baseURL: baseURL,
            urlSession: urlSession
        )
        request.setValue(
            "Bearer \(session.betaAccessToken)",
            forHTTPHeaderField: "Authorization"
        )
        request.setValue(
            credentialStore.installationId,
            forHTTPHeaderField: "X-Sift-Installation"
        )
        if includesProviderKey {
            guard let providerKey = credentialStore.providerKey, !providerKey.isEmpty else {
                throw SiftAPIError.providerKeyRequired
            }
            request.setValue(providerKey, forHTTPHeaderField: "X-Sift-Provider-Key")
        }
    }

    private func managedSettings(
        from connection: ManagedProviderConnectionDTO
    ) -> ModelProviderSettingsDTO {
        ModelProviderSettingsDTO(
            providerType: connection.providerId,
            baseURL: connection.baseURL,
            apiKeyConfigured: credentialStore.providerKey?.isEmpty == false,
            apiKeyPreview: credentialStore.providerKey.map { "***\($0.suffix(4))" },
            explainModel: connection.model,
            webSearchEnabled: true,
            supportsWebSearch: true
        )
    }
}

enum SiftAPIError: LocalizedError {
    case invalidResponse
    case httpStatus(Int, detail: SiftAPIErrorDetail?)
    case betaActivationRequired
    case providerKeyRequired
    case managedUnsupported

    var errorDescription: String? {
        switch self {
        case .invalidResponse:
            "The server returned an invalid response."
        case .httpStatus(let status, let detail):
            if let detail {
                "Server \(status): \(detail.displayMessage)"
            } else {
                "The server returned status \(status)."
            }
        case .betaActivationRequired:
            "Activate beta access to continue."
        case .providerKeyRequired:
            "Add your provider API key to continue."
        case .managedUnsupported:
            "This setting is not available in the managed beta."
        }
    }
}

private extension String {
    func siftChunks(maxLength: Int) -> [String] {
        guard maxLength > 0, !isEmpty else { return [] }
        var result: [String] = []
        var index = startIndex
        while index < endIndex {
            let next = self.index(index, offsetBy: maxLength, limitedBy: endIndex) ?? endIndex
            result.append(String(self[index..<next]))
            index = next
        }
        return result
    }
}

private struct EmptyRequest: Codable {}
private struct EmptyResponse: Codable {}

private struct SiftAPIErrorEnvelope: Decodable {
    var detail: SiftAPIErrorDetail?
    var error: SiftAPIErrorDetail?

    var resolvedDetail: SiftAPIErrorDetail? { error ?? detail }
}

struct SiftAPIErrorDetail: Decodable {
    var code: String?
    var message: String

    var displayMessage: String {
        switch code {
        case "invite_invalid": return "That invite code is invalid."
        case "invite_consumed": return "That invite code has already been used on another device."
        case "invalid_provider_key": return "Check your provider API key and try again."
        case "provider_quota_exhausted": return "Your provider quota is used up."
        case "provider_unreachable": return "Your provider could not be reached. Try again."
        case "backend_unavailable": return "Sift is temporarily unavailable. Try again."
        case "owner_scope_not_found": return "That item is no longer available."
        default: break
        }
        let normalized = message.lowercased()
        if normalized.contains("billing_not_active") {
            return "Runtime provider billing is not active. Enable billing with the selected provider, then retry."
        }
        if normalized.contains("invalid_json_schema") {
            return "The backend sent an invalid runtime response schema. Update the backend and retry."
        }
        if normalized.contains("rate_limit") || normalized.contains("too many requests") {
            return "Runtime provider rate limit reached. Wait a moment, then retry."
        }
        if normalized.contains("invalid api key") || normalized.contains("incorrect api key") {
            return "The runtime provider API key is invalid. Update the provider settings, then retry."
        }
        if let code, !code.isEmpty {
            return "\(code): \(message)"
        }
        return message
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if let message = try? container.decode(String.self) {
            self.code = nil
            self.message = message
            return
        }

        let object = try decoder.container(keyedBy: CodingKeys.self)
        self.code = try object.decodeIfPresent(String.self, forKey: .code)
        self.message = try object.decodeIfPresent(String.self, forKey: .message)
            ?? self.code
            ?? "Request failed."
    }

    private enum CodingKeys: String, CodingKey {
        case code
        case message
    }
}
