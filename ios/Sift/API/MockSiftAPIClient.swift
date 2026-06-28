import Foundation

struct MockSiftAPIClient: SiftAPIClient {
    var delayNanoseconds: UInt64 = 250_000_000

    var backendDescription: String {
        "Preview mock"
    }

    func getAppStatus() async throws -> AppStatusDTO {
        try await Task.sleep(nanoseconds: delayNanoseconds)
        return AppStatusDTO(
            env: "preview",
            modelProvider: "mock",
            explainModel: "preview",
            webSearchEnabled: false,
            databaseURL: "memory",
            providerBaseURL: nil,
            apiKeyConfigured: false,
            apiKeyPreview: nil
        )
    }

    func getModelProviderSettings() async throws -> ModelProviderSettingsDTO {
        try await Task.sleep(nanoseconds: delayNanoseconds)
        return ModelProviderSettingsDTO(
            providerType: "custom",
            baseURL: "https://api.openai.com/v1",
            apiKeyConfigured: true,
            apiKeyPreview: "***1234",
            explainModel: "gpt-5.5",
            webSearchEnabled: true,
            supportsWebSearch: true
        )
    }

    func updateModelProviderSettings(
        _ request: UpdateModelProviderSettingsRequest
    ) async throws -> ModelProviderSettingsDTO {
        try await Task.sleep(nanoseconds: delayNanoseconds)
        return ModelProviderSettingsDTO(
            providerType: request.providerType,
            baseURL: request.baseURL,
            apiKeyConfigured: request.apiKey?.isEmpty == false,
            apiKeyPreview: request.apiKey.map { "***\($0.suffix(4))" },
            explainModel: request.explainModel,
            webSearchEnabled: request.webSearchEnabled,
            supportsWebSearch: request.providerType != "mock"
        )
    }

    func listRuntimeModelProviders() async throws -> RuntimeProviderCatalogDTO {
        try await Task.sleep(nanoseconds: delayNanoseconds)
        return RuntimeProviderCatalogDTO(
            providers: [
                RuntimeProviderOptionDTO(
                    id: "deepseek",
                    name: "DeepSeek",
                    description: "DeepSeek via OpenAI-compatible chat completions.",
                    adapter: "openai_compatible",
                    apiMode: "chat_completions",
                    protocolDriver: "ChatCompletionsDriver",
                    hermesPluginPath: "plugins/model-providers/deepseek/__init__.py",
                    exposureTier: "plannedStable",
                    defaultBaseURL: "https://api.deepseek.com/v1",
                    defaultModel: "deepseek-chat",
                    requiresApiKey: true,
                    supportsModelListing: true,
                    status: "available",
                    isAdvanced: false
                ),
                RuntimeProviderOptionDTO(
                    id: "anthropic",
                    name: "Anthropic",
                    description: "Claude native Messages API provider.",
                    adapter: "anthropic_messages",
                    apiMode: "anthropic_messages",
                    protocolDriver: "AnthropicMessagesDriver",
                    hermesPluginPath: "plugins/model-providers/anthropic/__init__.py",
                    exposureTier: "plannedStable",
                    defaultBaseURL: "https://api.anthropic.com",
                    defaultModel: "claude-haiku-4-5-20251001",
                    requiresApiKey: true,
                    supportsModelListing: true,
                    status: "available",
                    isAdvanced: false
                )
            ]
        )
    }

    func listRuntimeWebProviders() async throws -> WebProviderCatalogDTO {
        try await Task.sleep(nanoseconds: delayNanoseconds)
        return WebProviderCatalogDTO(
            providers: [
                WebProviderOptionDTO(
                    id: "ddgs",
                    name: "DuckDuckGo",
                    description: "DuckDuckGo search via ddgs; no API key required.",
                    requiresApiKey: false,
                    supportsSearch: true,
                    supportsExtract: false,
                    status: "available",
                    isDefault: true
                ),
                WebProviderOptionDTO(
                    id: "tavily",
                    name: "Tavily",
                    description: "Search and extraction via Tavily.",
                    requiresApiKey: true,
                    supportsSearch: true,
                    supportsExtract: true,
                    status: "available",
                    isDefault: false
                )
            ]
        )
    }

    func getWebProviderSettings() async throws -> WebProviderSettingsDTO {
        try await Task.sleep(nanoseconds: delayNanoseconds)
        return WebProviderSettingsDTO(
            providerType: "ddgs",
            apiKeyConfigured: false,
            apiKeyPreview: nil,
            webSearchEnabled: true
        )
    }

    func updateWebProviderSettings(
        _ request: UpdateWebProviderSettingsRequest
    ) async throws -> WebProviderSettingsDTO {
        try await Task.sleep(nanoseconds: delayNanoseconds)
        return WebProviderSettingsDTO(
            providerType: request.providerType,
            apiKeyConfigured: request.apiKey?.isEmpty == false,
            apiKeyPreview: request.apiKey.map { "***\($0.suffix(4))" },
            webSearchEnabled: request.webSearchEnabled
        )
    }

    func listProviderModels() async throws -> ProviderModelListDTO {
        try await Task.sleep(nanoseconds: delayNanoseconds)
        return ProviderModelListDTO(
            models: [
                ProviderModelDTO(id: "gpt-5.5", ownedBy: "openai"),
                ProviderModelDTO(id: "deepseek-chat", ownedBy: "deepseek")
            ]
        )
    }

    func runModelDiagnostic() async throws -> ModelDiagnosticDTO {
        try await Task.sleep(nanoseconds: delayNanoseconds)
        return ModelDiagnosticDTO(
            ok: true,
            provider: "mock",
            model: "preview",
            message: "Preview mock responses are active.",
            webSearchUsed: nil,
            citationCount: nil
        )
    }

    func runWebSearchDiagnostic() async throws -> ModelDiagnosticDTO {
        try await Task.sleep(nanoseconds: delayNanoseconds)
        return ModelDiagnosticDTO(
            ok: false,
            provider: "mock",
            model: "preview",
            message: "A runtime web search provider key is required for diagnostics.",
            webSearchUsed: false,
            citationCount: 0
        )
    }

    func listConcepts() async throws -> [ConceptDTO] {
        try await Task.sleep(nanoseconds: delayNanoseconds)
        return []
    }

    func getConcept(id: UUID) async throws -> ConceptDTO {
        try await Task.sleep(nanoseconds: delayNanoseconds)
        return ConceptDTO(
            id: id,
            canonicalTitle: "RAG",
            displayTitle: "RAG",
            oneLineExplanation: "Retrieval-augmented generation improves answers with retrieved context.",
            maturity: ConceptMaturity.growing.rawValue,
            captureStatus: CaptureStatus.ready.rawValue,
            noteRevision: 1,
            blocks: []
        )
    }

    func updateConceptSummary(id: UUID, request: UpdateConceptSummaryRequest) async throws -> ConceptDTO {
        try await Task.sleep(nanoseconds: delayNanoseconds)
        return ConceptDTO(
            id: id,
            canonicalTitle: request.displayTitle,
            displayTitle: request.displayTitle,
            oneLineExplanation: request.oneLineExplanation,
            maturity: ConceptMaturity.growing.rawValue,
            captureStatus: CaptureStatus.ready.rawValue,
            noteRevision: 2,
            blocks: []
        )
    }

    func updateNoteBlock(
        conceptId: UUID,
        blockId: UUID,
        request: UpdateNoteBlockRequest
    ) async throws -> ConceptDTO {
        try await Task.sleep(nanoseconds: delayNanoseconds)
        return ConceptDTO(
            id: conceptId,
            canonicalTitle: "RAG",
            displayTitle: "RAG",
            oneLineExplanation: "Retrieval-augmented generation improves answers with retrieved context.",
            maturity: ConceptMaturity.growing.rawValue,
            captureStatus: CaptureStatus.ready.rawValue,
            noteRevision: 2,
            blocks: [
                NoteBlockDTO(
                    id: blockId,
                    blockType: NoteBlockType.whatItIs.rawValue,
                    content: request.content,
                    source: NoteBlockSource.user.rawValue,
                    isUserLocked: true
                )
            ]
        )
    }

    func updateConceptNote(
        id: UUID,
        request: UpdateConceptNoteRequest
    ) async throws -> ConceptDTO {
        try await Task.sleep(nanoseconds: delayNanoseconds)
        return ConceptDTO(
            id: id,
            canonicalTitle: request.displayTitle,
            displayTitle: request.displayTitle,
            oneLineExplanation: request.oneLineExplanation,
            maturity: ConceptMaturity.growing.rawValue,
            captureStatus: CaptureStatus.ready.rawValue,
            noteRevision: 2,
            blocks: request.blocks.enumerated().map { index, block in
                NoteBlockDTO(
                    id: block.id ?? UUID(),
                    blockType: block.blockType,
                    content: block.content,
                    source: NoteBlockSource.user.rawValue,
                    isUserLocked: true,
                    position: index
                )
            },
            tags: request.tags,
            topics: request.topics
        )
    }

    func updateConceptOrganization(
        id: UUID,
        request: UpdateConceptOrganizationRequest
    ) async throws -> ConceptDTO {
        try await Task.sleep(nanoseconds: delayNanoseconds)
        return ConceptDTO(
            id: id,
            canonicalTitle: "RAG",
            displayTitle: "RAG",
            oneLineExplanation: "Retrieval-augmented generation improves answers with retrieved context.",
            maturity: ConceptMaturity.growing.rawValue,
            captureStatus: CaptureStatus.ready.rawValue,
            noteRevision: 2,
            blocks: [],
            tags: request.tags,
            topics: request.topics
        )
    }

    func addRelation(conceptId: UUID, request: CreateConceptRelationRequest) async throws -> ConceptDTO {
        try await Task.sleep(nanoseconds: delayNanoseconds)
        return ConceptDTO(
            id: conceptId,
            canonicalTitle: "RAG",
            displayTitle: "RAG",
            oneLineExplanation: "Retrieval-augmented generation improves answers with retrieved context.",
            maturity: ConceptMaturity.growing.rawValue,
            captureStatus: CaptureStatus.ready.rawValue,
            noteRevision: 1,
            blocks: [],
            relations: [
                ConceptRelationDTO(
                    id: UUID(),
                    sourceConceptId: conceptId,
                    targetConceptId: request.targetConceptId,
                    relationType: request.relationType,
                    status: "accepted",
                    confidence: 1,
                    source: "user"
                )
            ]
        )
    }

    func removeRelation(conceptId: UUID, relationId: UUID) async throws -> ConceptDTO {
        try await Task.sleep(nanoseconds: delayNanoseconds)
        return ConceptDTO(
            id: conceptId,
            canonicalTitle: "RAG",
            displayTitle: "RAG",
            oneLineExplanation: "Retrieval-augmented generation improves answers with retrieved context.",
            maturity: ConceptMaturity.growing.rawValue,
            captureStatus: CaptureStatus.ready.rawValue,
            noteRevision: 1,
            blocks: [],
            relations: []
        )
    }

    func listTurns(conceptId: UUID) async throws -> [ConceptHistoryTurnDTO] {
        try await Task.sleep(nanoseconds: delayNanoseconds)
        return []
    }

    func createConcept(_ request: CreateConceptRequest) async throws -> ConceptDTO {
        try await createConcept(request, idempotencyKey: nil)
    }

    func createConcept(
        _ request: CreateConceptRequest,
        idempotencyKey: UUID?
    ) async throws -> ConceptDTO {
        try await Task.sleep(nanoseconds: delayNanoseconds)

        return ConceptDTO(
            id: UUID(),
            canonicalTitle: request.rawCapture.trimmingCharacters(in: .whitespacesAndNewlines),
            displayTitle: request.rawCapture.trimmingCharacters(in: .whitespacesAndNewlines),
            oneLineExplanation: "A first-pass explanation generated for local preview.",
            maturity: ConceptMaturity.initial.rawValue,
            captureStatus: CaptureStatus.ready.rawValue,
            noteRevision: 1,
            blocks: [
                NoteBlockDTO(
                    id: UUID(),
                    blockType: NoteBlockType.whatItIs.rawValue,
                    content: "A concise explanation will appear here.",
                    source: NoteBlockSource.ai.rawValue,
                    isUserLocked: false
                ),
                NoteBlockDTO(
                    id: UUID(),
                    blockType: NoteBlockType.whyItMatters.rawValue,
                    content: "Sift keeps this concept available for future follow-up.",
                    source: NoteBlockSource.ai.rawValue,
                    isUserLocked: false
                )
            ]
        )
    }

    func submitTurn(conceptId: UUID, request: ConceptTurnRequest) async throws -> ConceptTurnResponse {
        try await submitTurn(conceptId: conceptId, request: request, idempotencyKey: nil)
    }

    func submitTurn(
        conceptId: UUID,
        request: ConceptTurnRequest,
        idempotencyKey: UUID?
    ) async throws -> ConceptTurnResponse {
        try await Task.sleep(nanoseconds: delayNanoseconds)

        let concept = ConceptDTO(
            id: conceptId,
            canonicalTitle: "RAG",
            displayTitle: "RAG",
            oneLineExplanation: "Retrieval-augmented generation improves answers with retrieved context.",
            maturity: ConceptMaturity.growing.rawValue,
            captureStatus: CaptureStatus.ready.rawValue,
            noteRevision: 2,
            blocks: []
        )

        return ConceptTurnResponse(
            answer: "RAG differs from fine-tuning because it retrieves external context at answer time.",
            answerSource: AnswerSourceDTO(
                sourceType: AnswerSourceType.modelKnowledge.rawValue,
                confidence: 0.72,
                uncertaintyNote: "Generated from model knowledge, no external sources cited."
            ),
            updateMode: UpdateMode.autoMerge.rawValue,
            concept: concept,
            proposal: nil
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
            Task {
                let response = try await submitTurn(
                    conceptId: conceptId,
                    request: request,
                    idempotencyKey: idempotencyKey
                )
                continuation.yield(ConceptTurnStreamEvent(type: "started", delta: nil, response: nil))
                for chunk in response.answer.chunked(maxLength: 12) {
                    try await Task.sleep(nanoseconds: 60_000_000)
                    continuation.yield(ConceptTurnStreamEvent(type: "delta", delta: chunk, response: nil))
                }
                continuation.yield(ConceptTurnStreamEvent(type: "completed", delta: nil, response: response))
                continuation.finish()
            }
        }
    }

    func mergeProposal(id: UUID) async throws -> ConceptDTO {
        try await mergeProposal(id: id, idempotencyKey: nil)
    }

    func mergeProposal(id: UUID, idempotencyKey: UUID?) async throws -> ConceptDTO {
        try await Task.sleep(nanoseconds: delayNanoseconds)

        return ConceptDTO(
            id: UUID(),
            canonicalTitle: "Merged Concept",
            displayTitle: "Merged Concept",
            oneLineExplanation: "Proposal merged.",
            maturity: ConceptMaturity.growing.rawValue,
            captureStatus: CaptureStatus.ready.rawValue,
            noteRevision: 2,
            blocks: []
        )
    }

    func dismissProposal(id: UUID) async throws {
        try await Task.sleep(nanoseconds: delayNanoseconds)
    }
}

private extension String {
    func chunked(maxLength: Int) -> [String] {
        guard maxLength > 0 else { return [self] }
        var chunks: [String] = []
        var start = startIndex
        while start < endIndex {
            let end = index(start, offsetBy: maxLength, limitedBy: endIndex) ?? endIndex
            chunks.append(String(self[start..<end]))
            start = end
        }
        return chunks
    }
}
