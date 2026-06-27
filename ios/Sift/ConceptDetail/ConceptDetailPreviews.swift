#if DEBUG
import SwiftData
import SwiftUI

// MARK: - Preview API client

/// Delegates everything to the mock client, but serves rich seeded content for
/// `getConcept`/`listTurns` so a previewed card keeps its blocks after `.task`.
private struct PreviewSiftAPIClient: SiftAPIClient {
    var base = MockSiftAPIClient()
    var concept: ConceptDTO
    var turns: [ConceptHistoryTurnDTO] = []

    var backendDescription: String { "Preview" }

    func getConcept(id: UUID) async throws -> ConceptDTO { concept }
    func listTurns(conceptId: UUID) async throws -> [ConceptHistoryTurnDTO] { turns }

    func getAppStatus() async throws -> AppStatusDTO { try await base.getAppStatus() }
    func getModelProviderSettings() async throws -> ModelProviderSettingsDTO { try await base.getModelProviderSettings() }
    func listRuntimeModelProviders() async throws -> RuntimeProviderCatalogDTO { try await base.listRuntimeModelProviders() }
    func listRuntimeWebProviders() async throws -> WebProviderCatalogDTO { try await base.listRuntimeWebProviders() }
    func updateModelProviderSettings(_ request: UpdateModelProviderSettingsRequest) async throws -> ModelProviderSettingsDTO { try await base.updateModelProviderSettings(request) }
    func getWebProviderSettings() async throws -> WebProviderSettingsDTO { try await base.getWebProviderSettings() }
    func updateWebProviderSettings(_ request: UpdateWebProviderSettingsRequest) async throws -> WebProviderSettingsDTO { try await base.updateWebProviderSettings(request) }
    func listProviderModels() async throws -> ProviderModelListDTO { try await base.listProviderModels() }
    func runModelDiagnostic() async throws -> ModelDiagnosticDTO { try await base.runModelDiagnostic() }
    func runWebSearchDiagnostic() async throws -> ModelDiagnosticDTO { try await base.runWebSearchDiagnostic() }
    func listConcepts() async throws -> [ConceptDTO] { try await base.listConcepts() }
    func updateConceptSummary(id: UUID, request: UpdateConceptSummaryRequest) async throws -> ConceptDTO { concept }
    func updateNoteBlock(conceptId: UUID, blockId: UUID, request: UpdateNoteBlockRequest) async throws -> ConceptDTO { concept }
    func updateConceptOrganization(id: UUID, request: UpdateConceptOrganizationRequest) async throws -> ConceptDTO { concept }
    func addRelation(conceptId: UUID, request: CreateConceptRelationRequest) async throws -> ConceptDTO { concept }
    func removeRelation(conceptId: UUID, relationId: UUID) async throws -> ConceptDTO { concept }
    func createConcept(_ request: CreateConceptRequest) async throws -> ConceptDTO { concept }
    func submitTurn(conceptId: UUID, request: ConceptTurnRequest) async throws -> ConceptTurnResponse { try await base.submitTurn(conceptId: conceptId, request: request) }
    func streamTurn(conceptId: UUID, request: ConceptTurnRequest) -> AsyncThrowingStream<ConceptTurnStreamEvent, Error> { base.streamTurn(conceptId: conceptId, request: request) }
    func mergeProposal(id: UUID) async throws -> ConceptDTO { concept }
    func dismissProposal(id: UUID) async throws {}
}

// MARK: - Seed data

private enum ConceptPreview {
    static let conceptId = UUID(uuidString: "00000000-0000-0000-0000-0000000000A1")!
    static let relatedId = UUID(uuidString: "00000000-0000-0000-0000-0000000000A2")!
    static let proposalId = UUID(uuidString: "00000000-0000-0000-0000-0000000000A3")!
    static let whatItIsBlockId = UUID(uuidString: "00000000-0000-0000-0000-0000000000B1")!

    static func richConcept(status: CaptureStatus, withRelations: Bool) -> ConceptDTO {
        ConceptDTO(
            id: conceptId,
            canonicalTitle: "Semantic Cache",
            displayTitle: "Semantic Cache",
            oneLineExplanation: "A cache keyed on the meaning of a request, so similar questions can reuse a stored answer.",
            maturity: ConceptMaturity.growing.rawValue,
            captureStatus: status.rawValue,
            noteRevision: 2,
            blocks: [
                NoteBlockDTO(
                    id: whatItIsBlockId,
                    blockType: NoteBlockType.whatItIs.rawValue,
                    content: "A semantic cache stores past requests and responses indexed by an embedding of their meaning, rather than an exact string key. A new request is embedded and matched against the store; a close-enough match returns the cached answer.",
                    source: NoteBlockSource.ai.rawValue,
                    isUserLocked: false
                ),
                NoteBlockDTO(
                    id: UUID(),
                    blockType: NoteBlockType.whyItMatters.rawValue,
                    content: "It cuts latency and cost for LLM systems by avoiding repeated generation for questions that are phrased differently but mean the same thing.",
                    source: NoteBlockSource.ai.rawValue,
                    isUserLocked: false
                ),
                NoteBlockDTO(
                    id: UUID(),
                    blockType: NoteBlockType.example.rawValue,
                    content: "“What’s your refund window?” and “How long do I have to return something?” embed close together, so the second hits the cached answer from the first.",
                    source: NoteBlockSource.ai.rawValue,
                    isUserLocked: false
                ),
                NoteBlockDTO(
                    id: UUID(),
                    blockType: NoteBlockType.commonMisunderstandings.rawValue,
                    content: "It is not a normal key-value cache. Matching is approximate, so the similarity threshold and staleness both need tuning to avoid wrong reuse.",
                    source: NoteBlockSource.ai.rawValue,
                    isUserLocked: false
                )
            ],
            tags: ["caching", "retrieval"],
            topics: ["LLM infrastructure"],
            relations: withRelations ? [
                ConceptRelationDTO(
                    id: UUID(),
                    sourceConceptId: conceptId,
                    targetConceptId: relatedId,
                    relationType: "related",
                    status: "accepted",
                    confidence: 1,
                    source: "user"
                )
            ] : []
        )
    }

    static func relatedConcept() -> ConceptDTO {
        ConceptDTO(
            id: relatedId,
            canonicalTitle: "Embedding",
            displayTitle: "Embedding",
            oneLineExplanation: "A vector that places text in a space where nearness means similar meaning.",
            maturity: ConceptMaturity.mature.rawValue,
            captureStatus: CaptureStatus.ready.rawValue,
            noteRevision: 1,
            blocks: []
        )
    }

    /// Remote follow-up turns (backend does not persist the initial capture).
    static let followUpTurns: [ConceptHistoryTurnDTO] = [
        ConceptHistoryTurnDTO(role: ConversationRole.user.rawValue, content: "How is it different from a normal cache?"),
        ConceptHistoryTurnDTO(role: ConversationRole.assistant.rawValue, content: "A normal cache needs an exact key match. A semantic cache matches on meaning, so paraphrases still hit.")
    ]

    @MainActor
    static func container(
        status: CaptureStatus = .ready,
        withProposal: Bool = false,
        withInitialExchange: Bool = false,
        withRelations: Bool = true
    ) -> ModelContainer {
        let schema = Schema([
            Concept.self, ConceptNote.self, NoteBlock.self, NoteRevision.self,
            UpdateEvent.self, Conversation.self, ModelThread.self, ConversationMessage.self,
            ConceptUpdateProposal.self, AnswerSource.self, Tag.self, ConceptTag.self,
            Topic.self, ConceptTopic.self, ConceptRelation.self
        ])
        let container = try! ModelContainer(
            for: schema,
            configurations: ModelConfiguration(isStoredInMemoryOnly: true)
        )
        let context = container.mainContext
        let store = ConceptLocalStore(modelContext: context)
        _ = try! store.upsertConcept(from: relatedConcept())
        let concept = try! store.upsertConcept(from: richConcept(status: status, withRelations: withRelations))

        if withProposal {
            _ = try! store.upsertProposal(
                UpdateProposalDTO(
                    id: proposalId,
                    baseNoteRevision: 2,
                    patchOperations: [
                        PatchOperationDTO(
                            operation: "append",
                            targetBlockId: whatItIsBlockId,
                            content: "Add a line on how cache invalidation interacts with model updates."
                        )
                    ],
                    rationale: "Your follow-up clarified how often the underlying answers change, which is worth capturing on the card.",
                    confidence: 0.82,
                    status: ProposalStatus.proposed.rawValue
                ),
                conceptId: conceptId
            )
        }

        if withInitialExchange {
            // Mirror what CaptureFlowService persists: the original question as an
            // initialCapture user message, the first answer (when ready) as an
            // initialCapture assistant message, and a failed marker on failure.
            let conversation = Conversation(initialQuery: "What is a semantic cache?", concept: concept)
            concept.conversation = conversation
            context.insert(conversation)
            context.insert(ConversationMessage(
                role: ConversationRole.user.rawValue,
                content: "What is a semantic cache?",
                createdAt: .now,
                updateMode: LocalConversationMarker.initialCapture,
                conversation: conversation
            ))
            if status == .ready {
                context.insert(ConversationMessage(
                    role: ConversationRole.assistant.rawValue,
                    content: richConcept(status: status, withRelations: withRelations).oneLineExplanation,
                    createdAt: .now.addingTimeInterval(1),
                    updateMode: LocalConversationMarker.initialCapture,
                    conversation: conversation
                ))
            } else if status == .generationFailed {
                context.insert(ConversationMessage(
                    role: ConversationRole.assistant.rawValue,
                    content: "Generation failed: the model provider is unavailable.",
                    createdAt: .now.addingTimeInterval(1),
                    updateMode: LocalConversationMarker.failed,
                    conversation: conversation
                ))
            }
        }

        return container
    }

    static func services(status: CaptureStatus = .ready, withRelations: Bool = true, turns: [ConceptHistoryTurnDTO] = []) -> AppServices {
        AppServices(apiClient: PreviewSiftAPIClient(
            concept: richConcept(status: status, withRelations: withRelations),
            turns: turns
        ))
    }
}

// MARK: - Previews

#Preview("Reading Mode") {
    NavigationStack {
        ConceptDetailView(conceptId: ConceptPreview.conceptId, initialMode: .overview)
    }
    .modelContainer(ConceptPreview.container())
    .environment(\.appServices, ConceptPreview.services())
    .preferredColorScheme(.dark)
}

#Preview("Suggested Update") {
    NavigationStack {
        ConceptDetailView(conceptId: ConceptPreview.conceptId, initialMode: .overview)
    }
    .modelContainer(ConceptPreview.container(withProposal: true))
    .environment(\.appServices, ConceptPreview.services())
    .preferredColorScheme(.dark)
}

#Preview("Follow-up · Conversation") {
    NavigationStack {
        ConceptDetailView(conceptId: ConceptPreview.conceptId, initialMode: .followUp)
    }
    .modelContainer(ConceptPreview.container(withInitialExchange: true))
    .environment(\.appServices, ConceptPreview.services(turns: ConceptPreview.followUpTurns))
    .preferredColorScheme(.dark)
}

#Preview("Follow-up · Generating") {
    NavigationStack {
        ConceptDetailView(conceptId: ConceptPreview.conceptId, initialMode: .followUp)
    }
    .modelContainer(ConceptPreview.container(status: .generating, withInitialExchange: true, withRelations: false))
    .environment(\.appServices, ConceptPreview.services(status: .generating, withRelations: false))
    .preferredColorScheme(.dark)
}

#Preview("Follow-up · Generation failed") {
    NavigationStack {
        ConceptDetailView(conceptId: ConceptPreview.conceptId, initialMode: .followUp)
    }
    .modelContainer(ConceptPreview.container(status: .generationFailed, withInitialExchange: true, withRelations: false))
    .environment(\.appServices, ConceptPreview.services(status: .generationFailed, withRelations: false))
    .preferredColorScheme(.dark)
}
#endif
