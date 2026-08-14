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
    func previewProviderModels(
        _ request: UpdateModelProviderSettingsRequest
    ) async throws -> ProviderModelListDTO
    func runModelDiagnostic() async throws -> ModelDiagnosticDTO
    func runWebSearchDiagnostic() async throws -> ModelDiagnosticDTO
    func listConcepts() async throws -> [ConceptDTO]
    func getConcept(id: UUID) async throws -> ConceptDTO
    func archiveConcepts(ids: [UUID]) async throws -> [ConceptDTO]
    func restoreConcepts(ids: [UUID]) async throws -> [ConceptDTO]
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
    func listModelRuns(active: Bool) async throws -> [ModelRunDTO]
    func getModelRun(id: UUID) async throws -> ModelRunDTO
    func listModelRunEvents(id: UUID, afterSequence: Int) async throws -> [ModelRunEventDTO]
    func resumeModelRun(id: UUID) async throws -> ModelRunDTO
    func cancelModelRun(id: UUID) async throws -> ModelRunDTO
    func listProposals(conceptId: UUID, status: ProposalStatus?) async throws -> [UpdateProposalDTO]
    func listRevisions(conceptId: UUID) async throws -> [NoteRevisionSummaryDTO]
    func getRevision(conceptId: UUID, revision: Int) async throws -> NoteRevisionDTO
    func restoreRevision(conceptId: UUID, revision: Int) async throws -> ConceptDTO
    func createConcept(_ request: CreateConceptRequest) async throws -> ConceptDTO
    func createConcept(
        _ request: CreateConceptRequest,
        idempotencyKey: UUID?
    ) async throws -> ConceptDTO
    func streamCreateConcept(
        _ request: CreateConceptRequest,
        idempotencyKey: UUID?
    ) -> AsyncThrowingStream<ConceptInitialStreamEvent, Error>
    func streamCreateConcept(
        _ request: CreateConceptRequest,
        idempotencyKey: UUID?,
        clientDraftId: UUID?
    ) -> AsyncThrowingStream<ConceptInitialStreamEvent, Error>
    func streamResumeInitialConceptRun(
        id: UUID
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

    func previewProviderModels(
        _ request: UpdateModelProviderSettingsRequest
    ) async throws -> ProviderModelListDTO {
        _ = try await updateModelProviderSettings(request)
        return try await listProviderModels()
    }

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
                    if !answer.isEmpty {
                        continuation.yield(ConceptInitialStreamEvent(type: "delta", delta: answer, concept: nil))
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

    func streamCreateConcept(
        _ request: CreateConceptRequest,
        idempotencyKey: UUID?,
        clientDraftId: UUID?
    ) -> AsyncThrowingStream<ConceptInitialStreamEvent, Error> {
        streamCreateConcept(request, idempotencyKey: idempotencyKey)
    }

    func streamResumeInitialConceptRun(
        id: UUID
    ) -> AsyncThrowingStream<ConceptInitialStreamEvent, Error> {
        AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    let run = try await resumeModelRun(id: id)
                    continuation.yield(
                        ConceptInitialStreamEvent(type: "started", delta: nil, concept: nil, modelRun: run)
                    )
                    guard run.status == "succeeded", let concept = run.result?.concept else {
                        throw SiftAPIError.modelRunFailed(code: run.errorCode ?? "model_run_failed")
                    }
                    continuation.yield(
                        ConceptInitialStreamEvent(type: "completed", delta: nil, concept: concept, modelRun: run)
                    )
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

    func listModelRuns(active: Bool) async throws -> [ModelRunDTO] { [] }
    func getModelRun(id: UUID) async throws -> ModelRunDTO { throw SiftAPIError.invalidResponse }
    func listModelRunEvents(id: UUID, afterSequence: Int) async throws -> [ModelRunEventDTO] { [] }
    func resumeModelRun(id: UUID) async throws -> ModelRunDTO { throw SiftAPIError.invalidResponse }
    func cancelModelRun(id: UUID) async throws -> ModelRunDTO { try await getModelRun(id: id) }
    func listProposals(conceptId: UUID, status: ProposalStatus?) async throws -> [UpdateProposalDTO] { [] }
    func listRevisions(conceptId: UUID) async throws -> [NoteRevisionSummaryDTO] { [] }
    func getRevision(conceptId: UUID, revision: Int) async throws -> NoteRevisionDTO { throw SiftAPIError.invalidResponse }
    func restoreRevision(conceptId: UUID, revision: Int) async throws -> ConceptDTO { throw SiftAPIError.invalidResponse }
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
            let candidateProviderKey = request.apiKey.flatMap { $0.isEmpty ? nil : $0 }
            let managedRequest = ManagedProviderConnectionRequest(
                providerId: request.providerType,
                baseURL: request.baseURL,
                model: request.explainModel
            )
            let _: ManagedProviderTestDTO = try await post(
                path: "/v1/providers/test",
                body: managedRequest,
                includesProviderKey: true,
                providerKeyOverride: candidateProviderKey
            )
            let connection: ManagedProviderConnectionDTO = try await put(
                path: "/v1/provider-connection",
                body: managedRequest
            )
            if let candidateProviderKey {
                credentialStore.providerKey = candidateProviderKey
            }
            return managedSettings(from: connection)
        }
        return try await put(path: "/v1/model-provider-settings", body: request)
    }

    func getWebProviderSettings() async throws -> WebProviderSettingsDTO {
        let response: WebProviderSettingsDTO = try await get(path: "/v1/web-provider-settings")
        guard requiresBetaActivation else { return response }
        return WebProviderSettingsDTO(
            providerType: response.providerType,
            apiKeyConfigured: credentialStore.webProviderKey?.isEmpty == false,
            apiKeyPreview: credentialStore.webProviderKey.map { "***\($0.suffix(4))" },
            webSearchEnabled: response.webSearchEnabled
        )
    }

    func updateWebProviderSettings(
        _ request: UpdateWebProviderSettingsRequest
    ) async throws -> WebProviderSettingsDTO {
        if requiresBetaActivation {
            if let apiKey = request.apiKey, !apiKey.isEmpty {
                credentialStore.webProviderKey = apiKey
            }
            let response: WebProviderSettingsDTO = try await put(
                path: "/v1/web-provider-settings",
                body: UpdateWebProviderSettingsRequest(
                    providerType: request.providerType,
                    apiKey: nil,
                    webSearchEnabled: request.webSearchEnabled
                )
            )
            return WebProviderSettingsDTO(
                providerType: response.providerType,
                apiKeyConfigured: credentialStore.webProviderKey?.isEmpty == false,
                apiKeyPreview: credentialStore.webProviderKey.map { "***\($0.suffix(4))" },
                webSearchEnabled: response.webSearchEnabled
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

    func previewProviderModels(
        _ request: UpdateModelProviderSettingsRequest
    ) async throws -> ProviderModelListDTO {
        guard requiresBetaActivation else {
            _ = try await updateModelProviderSettings(request)
            return try await listProviderModels()
        }
        let candidateProviderKey = request.apiKey.flatMap { $0.isEmpty ? nil : $0 }
        return try await post(
            path: "/v1/providers/models",
            body: ManagedProviderConnectionRequest(
                providerId: request.providerType,
                baseURL: request.baseURL,
                model: request.explainModel
            ),
            includesProviderKey: true,
            providerKeyOverride: candidateProviderKey
        )
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
        try await post(
            path: "/v1/web-search-diagnostic",
            body: EmptyRequest(),
            includesWebProviderKey: requiresBetaActivation
        )
    }

    func listConcepts() async throws -> [ConceptDTO] {
        try await get(path: "/v1/concepts")
    }

    func getConcept(id: UUID) async throws -> ConceptDTO {
        try await get(path: "/v1/concepts/\(id.uuidString)")
    }

    func archiveConcepts(ids: [UUID]) async throws -> [ConceptDTO] {
        try await patch(path: "/v1/concepts/archive", body: BatchConceptRequest(conceptIds: ids))
    }

    func restoreConcepts(ids: [UUID]) async throws -> [ConceptDTO] {
        try await patch(path: "/v1/concepts/restore", body: BatchConceptRequest(conceptIds: ids))
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

    func listModelRuns(active: Bool) async throws -> [ModelRunDTO] {
        try await get(path: "/v1/model-runs", queryItems: [URLQueryItem(name: "active", value: active ? "true" : "false")])
    }

    func getModelRun(id: UUID) async throws -> ModelRunDTO {
        try await get(path: "/v1/model-runs/\(id.uuidString)")
    }

    func listModelRunEvents(id: UUID, afterSequence: Int) async throws -> [ModelRunEventDTO] {
        try await get(
            path: "/v1/model-runs/\(id.uuidString)/events",
            queryItems: [URLQueryItem(name: "afterSequence", value: String(afterSequence))]
        )
    }

    func resumeModelRun(id: UUID) async throws -> ModelRunDTO {
        try await post(
            path: "/v1/model-runs/\(id.uuidString)/resume",
            body: EmptyRequest(),
            includesProviderKey: requiresBetaActivation,
            includesWebProviderKey: requiresBetaActivation,
            timeoutInterval: 120
        )
    }

    func listProposals(
        conceptId: UUID,
        status: ProposalStatus?
    ) async throws -> [UpdateProposalDTO] {
        try await get(
            path: "/v1/concepts/\(conceptId.uuidString)/proposals",
            queryItems: status.map { [URLQueryItem(name: "status", value: $0.rawValue)] } ?? []
        )
    }

    func listRevisions(conceptId: UUID) async throws -> [NoteRevisionSummaryDTO] {
        try await get(path: "/v1/concepts/\(conceptId.uuidString)/revisions")
    }

    func getRevision(conceptId: UUID, revision: Int) async throws -> NoteRevisionDTO {
        try await get(path: "/v1/concepts/\(conceptId.uuidString)/revisions/\(revision)")
    }

    func restoreRevision(conceptId: UUID, revision: Int) async throws -> ConceptDTO {
        try await post(path: "/v1/concepts/\(conceptId.uuidString)/revisions/\(revision)/restore", body: EmptyRequest())
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
        streamCreateConcept(request, idempotencyKey: idempotencyKey, clientDraftId: nil)
    }

    func streamCreateConcept(
        _ request: CreateConceptRequest,
        idempotencyKey: UUID?,
        clientDraftId: UUID?
    ) -> AsyncThrowingStream<ConceptInitialStreamEvent, Error> {
        AsyncThrowingStream { continuation in
            Task {
                do {
                    do {
                        let run = try await submitModelRunRecovering(
                            path: "/v1/concept-runs",
                            body: CreateConceptRunRequest(
                                capture: request,
                                clientDraftId: clientDraftId?.uuidString
                            ),
                            idempotencyKey: idempotencyKey,
                            includesProviderKey: false,
                            includesWebProviderKey: false
                        )
                        continuation.yield(ConceptInitialStreamEvent(type: "started", delta: nil, concept: nil, modelRun: run))
                        let onEvent: (ModelRunEventDTO) -> Void = { event in
                            if event.type == "delta", let delta = event.data?.content {
                                continuation.yield(
                                    ConceptInitialStreamEvent(
                                        type: "delta",
                                        delta: delta,
                                        concept: nil,
                                        modelRun: run,
                                        sequence: event.sequence
                                    )
                                )
                            } else if event.type == "deltaReset" {
                                continuation.yield(
                                    ConceptInitialStreamEvent(
                                        type: "reset",
                                        delta: nil,
                                        concept: nil,
                                        modelRun: run,
                                        sequence: event.sequence
                                    )
                                )
                            } else if event.type == "sourcesReady",
                                      let citations = event.data?.citations,
                                      !citations.isEmpty {
                                continuation.yield(
                                    ConceptInitialStreamEvent(
                                        type: "sources",
                                        delta: nil,
                                        concept: nil,
                                        modelRun: run,
                                        sequence: event.sequence,
                                        citations: citations
                                    )
                                )
                            } else if ["stepStarted", "stepRestarted"].contains(event.type),
                                      let label = event.data?.label {
                                continuation.yield(
                                    ConceptInitialStreamEvent(
                                        type: "progress",
                                        delta: nil,
                                        concept: nil,
                                        modelRun: run,
                                        sequence: event.sequence,
                                        progressLabel: label
                                    )
                                )
                            }
                        }
                        let completed: ModelRunDTO
                        if requiresBetaActivation {
                            completed = try await waitForManagedModelRun(run, onEvent: onEvent)
                        } else {
                            completed = try await waitForModelRun(run, onEvent: onEvent)
                        }
                        guard let concept = completed.result?.concept else { throw SiftStreamingError.incomplete }
                        continuation.yield(ConceptInitialStreamEvent(type: "completed", delta: nil, concept: concept, modelRun: completed))
                    } catch SiftAPIError.httpStatus(404, _) {
                        try await streamPost(
                            path: "/v1/concepts/stream",
                            body: request,
                            idempotencyKey: idempotencyKey,
                            includesProviderKey: requiresBetaActivation,
                            continuation: continuation
                        )
                    }
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
        }
    }

    func streamResumeInitialConceptRun(
        id: UUID
    ) -> AsyncThrowingStream<ConceptInitialStreamEvent, Error> {
        AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    let run = try await getModelRun(id: id)
                    continuation.yield(
                        ConceptInitialStreamEvent(type: "started", delta: nil, concept: nil, modelRun: run)
                    )
                    let onEvent: (ModelRunEventDTO) -> Void = { event in
                        if let streamEvent = initialConceptStreamEvent(from: event, modelRun: run) {
                            continuation.yield(streamEvent)
                        }
                    }
                    let completed: ModelRunDTO
                    if requiresBetaActivation {
                        completed = try await waitForManagedModelRun(run, onEvent: onEvent)
                    } else {
                        let resumed = run.status == "failed" ? try await resumeModelRun(id: id) : run
                        completed = try await waitForModelRun(resumed, onEvent: onEvent)
                    }
                    guard let concept = completed.result?.concept else {
                        throw SiftStreamingError.incomplete
                    }
                    continuation.yield(
                        ConceptInitialStreamEvent(
                            type: "completed",
                            delta: nil,
                            concept: concept,
                            modelRun: completed
                        )
                    )
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { @Sendable _ in task.cancel() }
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
            includesProviderKey: requiresBetaActivation,
            includesWebProviderKey: requiresBetaActivation
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
                    do {
                        let run = try await submitModelRunRecovering(
                            path: "/v1/concepts/\(conceptId.uuidString)/turn-runs",
                            body: CreateTurnRunRequest(turn: request),
                            idempotencyKey: idempotencyKey,
                            includesProviderKey: false,
                            includesWebProviderKey: false
                        )
                        continuation.yield(ConceptTurnStreamEvent(type: "started", delta: nil, response: nil, modelRun: run))
                        let onEvent: (ModelRunEventDTO) -> Void = { event in
                            if event.type == "delta", let delta = event.data?.content {
                                continuation.yield(
                                    ConceptTurnStreamEvent(
                                        type: "delta",
                                        delta: delta,
                                        response: nil,
                                        modelRun: run,
                                        sequence: event.sequence
                                    )
                                )
                            } else if event.type == "deltaReset" {
                                continuation.yield(
                                    ConceptTurnStreamEvent(
                                        type: "reset",
                                        delta: nil,
                                        response: nil,
                                        modelRun: run,
                                        sequence: event.sequence
                                    )
                                )
                            } else if event.type == "sourcesReady",
                                      let citations = event.data?.citations,
                                      !citations.isEmpty {
                                continuation.yield(
                                    ConceptTurnStreamEvent(
                                        type: "sources",
                                        delta: nil,
                                        response: nil,
                                        modelRun: run,
                                        sequence: event.sequence,
                                        citations: citations
                                    )
                                )
                            } else if ["stepStarted", "stepRestarted"].contains(event.type),
                                      let label = event.data?.label {
                                continuation.yield(
                                    ConceptTurnStreamEvent(
                                        type: "progress",
                                        delta: nil,
                                        response: nil,
                                        modelRun: run,
                                        sequence: event.sequence,
                                        progressLabel: label
                                    )
                                )
                            }
                        }
                        let completed: ModelRunDTO
                        if requiresBetaActivation {
                            completed = try await waitForManagedModelRun(run, onEvent: onEvent)
                        } else {
                            completed = try await waitForModelRun(run, onEvent: onEvent)
                        }
                        guard let response = completed.result?.response else { throw SiftStreamingError.incomplete }
                        continuation.yield(ConceptTurnStreamEvent(type: "completed", delta: nil, response: response, modelRun: completed))
                    } catch SiftAPIError.httpStatus(404, _) {
                        try await streamPost(
                            path: "/v1/concepts/\(conceptId.uuidString)/turns/stream",
                            body: request,
                            idempotencyKey: idempotencyKey,
                            includesProviderKey: requiresBetaActivation,
                            includesWebProviderKey: requiresBetaActivation,
                            continuation: continuation
                        )
                    }
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

    private func initialConceptStreamEvent(
        from event: ModelRunEventDTO,
        modelRun: ModelRunDTO
    ) -> ConceptInitialStreamEvent? {
        if event.type == "delta", let delta = event.data?.content {
            return ConceptInitialStreamEvent(
                type: "delta",
                delta: delta,
                concept: nil,
                modelRun: modelRun,
                sequence: event.sequence
            )
        }
        if event.type == "deltaReset" {
            return ConceptInitialStreamEvent(
                type: "reset",
                delta: nil,
                concept: nil,
                modelRun: modelRun,
                sequence: event.sequence
            )
        }
        if event.type == "sourcesReady",
           let citations = event.data?.citations,
           !citations.isEmpty {
            return ConceptInitialStreamEvent(
                type: "sources",
                delta: nil,
                concept: nil,
                modelRun: modelRun,
                sequence: event.sequence,
                citations: citations
            )
        }
        if ["stepStarted", "stepRestarted"].contains(event.type),
           let label = event.data?.label {
            return ConceptInitialStreamEvent(
                type: "progress",
                delta: nil,
                concept: nil,
                modelRun: modelRun,
                sequence: event.sequence,
                progressLabel: label
            )
        }
        return nil
    }

    private func waitForModelRun(
        _ initial: ModelRunDTO,
        onEvent: (ModelRunEventDTO) -> Void
    ) async throws -> ModelRunDTO {
        var run = initial
        var lastSequence = 0
        while true {
            try Task.checkCancellation()
            if run.status == "waitingForCredential" {
                run = try await resumeModelRun(id: run.id)
            } else if ["queued", "running"].contains(run.status) {
                run = try await getModelRun(id: run.id)
            }
            let events = (try? await listModelRunEvents(
                id: run.id,
                afterSequence: lastSequence
            )) ?? []
            for event in events {
                guard event.sequence > lastSequence else { continue }
                lastSequence = event.sequence
                onEvent(event)
            }
            guard ["queued", "running", "waitingForCredential"].contains(run.status) else {
                break
            }
            try await Task.sleep(for: .milliseconds(250))
        }
        guard run.status == "succeeded" else {
            throw SiftAPIError.modelRunFailed(code: run.errorCode ?? "model_run_failed")
        }
        return run
    }

    private func waitForManagedModelRun(
        _ initial: ModelRunDTO,
        onEvent: (ModelRunEventDTO) -> Void
    ) async throws -> ModelRunDTO {
        guard ["queued", "running", "waitingForCredential", "failed"].contains(initial.status) else {
            return try await waitForModelRun(initial, onEvent: onEvent)
        }
        var receivedLiveDelta = false
        do {
            return try await streamResumeModelRun(id: initial.id) { event in
                if event.type == "delta" {
                    receivedLiveDelta = true
                }
                onEvent(event)
            }
        } catch is CancellationError {
            throw CancellationError()
        } catch let failure as SiftAPIError where failure.isHTTPStatus(404) {
            return try await waitForManagedModelRunByPolling(
                initial,
                replayPersistedDeltas: true,
                reconnectStream: false,
                onEvent: onEvent
            )
        } catch {
            guard isRecoverableManagedStreamFailure(error) else { throw error }
            return try await waitForManagedModelRunByPolling(
                initial,
                replayPersistedDeltas: !receivedLiveDelta,
                reconnectStream: true,
                onEvent: onEvent
            )
        }
    }

    private func waitForManagedModelRunByPolling(
        _ initial: ModelRunDTO,
        replayPersistedDeltas: Bool,
        reconnectStream: Bool,
        onEvent: (ModelRunEventDTO) -> Void
    ) async throws -> ModelRunDTO {
        var run = initial
        var lastSequence = 0
        var shouldReconnectStream = reconnectStream
        let deadline = Date().addingTimeInterval(125)

        while true {
            try Task.checkCancellation()
            guard Date() < deadline else {
                throw SiftAPIError.modelRunFailed(code: "model_run_timeout")
            }
            let events = (try? await listModelRunEvents(
                id: run.id,
                afterSequence: lastSequence
            )) ?? []
            for event in events {
                guard event.sequence > lastSequence else { continue }
                lastSequence = event.sequence
                if replayPersistedDeltas || event.type != "delta" {
                    onEvent(event)
                }
            }
            guard ["queued", "running", "waitingForCredential"].contains(run.status) else {
                break
            }
            if shouldReconnectStream {
                do {
                    return try await streamResumeModelRun(id: run.id, onEvent: onEvent)
                } catch is CancellationError {
                    throw CancellationError()
                } catch let failure as SiftAPIError where failure.isHTTPStatus(404) {
                    shouldReconnectStream = false
                } catch {
                    guard isRecoverableManagedStreamFailure(error) else { throw error }
                }
            }
            try await Task.sleep(for: .milliseconds(500))
            do {
                run = try await getModelRun(id: run.id)
            } catch is CancellationError {
                throw CancellationError()
            } catch {
                guard isRecoverableManagedStreamFailure(error) else { throw error }
            }
        }
        let terminalEvents = (try? await listModelRunEvents(
            id: run.id,
            afterSequence: lastSequence
        )) ?? []
        for event in terminalEvents {
            guard event.sequence > lastSequence else { continue }
            lastSequence = event.sequence
            if replayPersistedDeltas || event.type != "delta" {
                onEvent(event)
            }
        }
        guard run.status == "succeeded" else {
            throw SiftAPIError.modelRunFailed(code: run.errorCode ?? "model_run_failed")
        }
        return run
    }

    private func isRecoverableManagedStreamFailure(_ error: Error) -> Bool {
        if error is URLError { return true }
        if let failure = error as? SiftStreamingError {
            if case .incomplete = failure { return true }
            return false
        }
        guard let failure = error as? SiftAPIError else { return false }
        switch failure {
        case .invalidResponse:
            return true
        case .httpStatus(let status, _):
            return [408, 409, 425, 429].contains(status) || (500...599).contains(status)
        case .modelRunFailed, .betaActivationRequired, .providerKeyRequired, .managedUnsupported:
            return false
        }
    }

    private func streamResumeModelRun(
        id: UUID,
        onEvent: (ModelRunEventDTO) -> Void
    ) async throws -> ModelRunDTO {
        var urlRequest = URLRequest(
            url: baseURL.appending(path: "/v1/model-runs/\(id.uuidString)/resume-stream")
        )
        urlRequest.httpMethod = "POST"
        urlRequest.timeoutInterval = 125
        urlRequest.setValue("application/x-ndjson", forHTTPHeaderField: "Accept")
        try await authorize(
            &urlRequest,
            includesProviderKey: true,
            includesWebProviderKey: true
        )

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

        var sequence = 0
        for try await line in bytes.lines {
            try Task.checkCancellation()
            guard !line.isEmpty, let data = line.data(using: .utf8) else { continue }
            let event = try jsonDecoder.decode(ModelRunExecutionStreamEventDTO.self, from: data)
            switch event.type {
            case "progress":
                sequence = max(sequence + 1, event.sequence ?? 0)
                onEvent(
                    ModelRunEventDTO(
                        sequence: sequence,
                        type: "stepStarted",
                        data: .init(label: event.progressLabel),
                        createdAt: .now
                    )
                )
            case "delta":
                guard let delta = event.delta, !delta.isEmpty else { continue }
                sequence += 1
                onEvent(
                    ModelRunEventDTO(
                        sequence: sequence,
                        type: "delta",
                        data: .init(content: delta),
                        createdAt: .now
                    )
                )
            case "reset":
                sequence = max(sequence + 1, event.sequence ?? 0)
                onEvent(
                    ModelRunEventDTO(
                        sequence: sequence,
                        type: "deltaReset",
                        createdAt: .now
                    )
                )
            case "sources":
                guard let citations = event.citations, !citations.isEmpty else { continue }
                sequence = max(sequence + 1, event.sequence ?? 0)
                onEvent(
                    ModelRunEventDTO(
                        sequence: sequence,
                        type: "sourcesReady",
                        data: .init(citations: citations),
                        createdAt: .now
                    )
                )
            case "completed":
                guard let completed = event.modelRun else {
                    throw SiftStreamingError.incomplete
                }
                guard completed.status == "succeeded" else {
                    if completed.status == "cancelled" {
                        throw CancellationError()
                    }
                    if completed.status == "failed" {
                        throw SiftAPIError.modelRunFailed(
                            code: completed.errorCode ?? "model_run_failed"
                        )
                    }
                    throw SiftStreamingError.incomplete
                }
                return completed
            case "failed":
                throw SiftAPIError.modelRunFailed(
                    code: event.errorCode ?? "model_run_failed"
                )
            case "cancelled":
                throw CancellationError()
            case "detached":
                throw SiftStreamingError.incomplete
            default:
                continue
            }
        }
        throw SiftStreamingError.incomplete
    }

    func cancelModelRun(id: UUID) async throws -> ModelRunDTO {
        try await post(
            path: "/v1/model-runs/\(id.uuidString)/cancel",
            body: EmptyRequest()
        )
    }

    private func get<Response: Decodable>(path: String, queryItems: [URLQueryItem] = []) async throws -> Response {
        var components = URLComponents(url: baseURL.appending(path: path), resolvingAgainstBaseURL: false)!
        components.queryItems = queryItems.isEmpty ? nil : queryItems
        var urlRequest = URLRequest(url: components.url!)
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
        includesProviderKey: Bool = false,
        providerKeyOverride: String? = nil,
        includesWebProviderKey: Bool = false,
        timeoutInterval: TimeInterval? = nil
    ) async throws -> Response {
        var urlRequest = URLRequest(url: baseURL.appending(path: path))
        urlRequest.httpMethod = "POST"
        if let timeoutInterval {
            urlRequest.timeoutInterval = timeoutInterval
        }
        urlRequest.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let idempotencyKey {
            urlRequest.setValue(idempotencyKey.uuidString, forHTTPHeaderField: "Idempotency-Key")
        }
        if authorized {
            try await authorize(
                &urlRequest,
                includesProviderKey: includesProviderKey,
                providerKeyOverride: providerKeyOverride,
                includesWebProviderKey: includesWebProviderKey
            )
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

    private func submitModelRunRecovering<Request: Encodable>(
        path: String,
        body: Request,
        idempotencyKey: UUID?,
        includesProviderKey: Bool = false,
        includesWebProviderKey: Bool = false
    ) async throws -> ModelRunDTO {
        do {
            return try await post(
                path: path,
                body: body,
                idempotencyKey: idempotencyKey,
                includesProviderKey: includesProviderKey,
                includesWebProviderKey: includesWebProviderKey
            )
        } catch {
            guard idempotencyKey != nil, isRecoverableIdempotentWriteFailure(error) else {
                throw error
            }
            if let idempotencyKey,
               let recovered = try? await recoverModelRun(idempotencyKey: idempotencyKey) {
                return recovered
            }
            try await Task.sleep(for: .milliseconds(250))
            do {
                return try await post(
                    path: path,
                    body: body,
                    idempotencyKey: idempotencyKey,
                    includesProviderKey: includesProviderKey,
                    includesWebProviderKey: includesWebProviderKey
                )
            } catch {
                if let idempotencyKey,
                   isRecoverableIdempotentWriteFailure(error),
                   let recovered = try? await recoverModelRun(idempotencyKey: idempotencyKey) {
                    return recovered
                }
                throw error
            }
        }
    }

    private func recoverModelRun(idempotencyKey: UUID) async throws -> ModelRunDTO? {
        let runs: [ModelRunDTO] = try await get(
            path: "/v1/model-runs",
            queryItems: [URLQueryItem(name: "active", value: "false")]
        )
        return runs.first { UUID(uuidString: $0.idempotencyKey) == idempotencyKey }
    }

    private func isRecoverableIdempotentWriteFailure(_ error: Error) -> Bool {
        if error is URLError { return true }
        if case SiftAPIError.invalidResponse = error { return true }
        if case SiftAPIError.httpStatus(let status, _) = error {
            return (500...599).contains(status)
        }
        return false
    }

    private func streamPost<Request: Encodable, Event: Decodable>(
        path: String,
        body: Request,
        idempotencyKey: UUID? = nil,
        includesProviderKey: Bool = false,
        includesWebProviderKey: Bool = false,
        continuation: AsyncThrowingStream<Event, Error>.Continuation
    ) async throws {
        var urlRequest = URLRequest(url: baseURL.appending(path: path))
        urlRequest.httpMethod = "POST"
        urlRequest.setValue("application/json", forHTTPHeaderField: "Content-Type")
        urlRequest.setValue("application/x-ndjson", forHTTPHeaderField: "Accept")
        if let idempotencyKey {
            urlRequest.setValue(idempotencyKey.uuidString, forHTTPHeaderField: "Idempotency-Key")
        }
        try await authorize(
            &urlRequest,
            includesProviderKey: includesProviderKey,
            includesWebProviderKey: includesWebProviderKey
        )
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
        includesProviderKey: Bool = false,
        providerKeyOverride: String? = nil,
        includesWebProviderKey: Bool = false
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
            guard let providerKey = providerKeyOverride ?? credentialStore.providerKey,
                  !providerKey.isEmpty else {
                throw SiftAPIError.providerKeyRequired
            }
            request.setValue(providerKey, forHTTPHeaderField: "X-Sift-Provider-Key")
        }
        if includesWebProviderKey,
           let webProviderKey = credentialStore.webProviderKey,
           !webProviderKey.isEmpty {
            request.setValue(webProviderKey, forHTTPHeaderField: "X-Sift-Web-Provider-Key")
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
    case modelRunFailed(code: String)
    case httpStatus(Int, detail: SiftAPIErrorDetail?)
    case betaActivationRequired
    case providerKeyRequired
    case managedUnsupported

    fileprivate func isHTTPStatus(_ expectedStatus: Int) -> Bool {
        guard case .httpStatus(let status, _) = self else { return false }
        return status == expectedStatus
    }

    var errorDescription: String? {
        switch self {
        case .invalidResponse:
            "The server returned an invalid response."
        case .modelRunFailed(let code):
            "The agent run stopped safely (\(code))."
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
