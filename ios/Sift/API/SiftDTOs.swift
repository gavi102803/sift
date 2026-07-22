import Foundation

struct BetaSessionDTO: Codable {
    var betaAccessToken: String
    var ownerId: String
    var expiresAt: Date
}

struct ActivateBetaRequest: Codable {
    var inviteCode: String
    var installationId: String
}

struct ManagedProviderConnectionDTO: Codable {
    var providerId: String
    var baseURL: String
    var model: String
}

struct ManagedProviderConnectionRequest: Codable {
    var providerId: String
    var baseURL: String?
    var model: String
}

struct ManagedProviderTestDTO: Codable {
    var ok: Bool
}

struct CreateConceptRequest: Codable {
    var rawCapture: String
    var locale: String
}

struct CreateConceptRunRequest: Codable {
    var capture: CreateConceptRequest
    var clientDraftId: String?
}

struct CreateTurnRunRequest: Codable {
    var turn: ConceptTurnRequest
}

struct ModelRunResultDTO: Codable {
    var concept: ConceptDTO?
    var response: ConceptTurnResponse?
    var proposal: UpdateProposalDTO? = nil
}

struct ModelRunDTO: Codable, Identifiable {
    var id: UUID
    var kind: String
    var status: String
    var conceptId: UUID?
    var clientDraftId: String?
    var idempotencyKey: String
    var providerSnapshot: [String: String] = [:]
    var agentSpec: String?
    var agentSpecVersion: String?
    var promptVersion: String?
    var budget: [String: Int]?
    var currentStep: String?
    var modelCallCount: Int?
    var toolCallCount: Int?
    var terminationReason: String?
    var dependencyRunId: UUID?
    var checkpoint: String?
    var result: ModelRunResultDTO?
    var resultRef: String?
    var errorCode: String?
    var errorMessage: String?
    var childRunIds: [UUID]
    var createdAt: Date
    var updatedAt: Date
}

struct ModelRunEventDTO: Codable, Identifiable {
    struct DataPayload: Codable {
        var content: String?
        var step: String?
        var label: String?
        var modelCalls: Int?
        var toolCalls: Int?
    }

    var sequence: Int
    var type: String
    var data: DataPayload? = nil
    var createdAt: Date
    var id: Int { sequence }
}

struct AppStatusDTO: Codable {
    var env: String
    var modelProvider: String
    var explainModel: String
    var webSearchEnabled: Bool
    var databaseURL: String
    var providerBaseURL: String? = nil
    var apiKeyConfigured: Bool? = nil
    var apiKeyPreview: String? = nil
}

struct ModelDiagnosticDTO: Codable {
    var ok: Bool
    var provider: String
    var model: String
    var message: String
    var webSearchUsed: Bool?
    var citationCount: Int?
}

struct ModelProviderSettingsDTO: Codable {
    var providerType: String
    var baseURL: String
    var apiKeyConfigured: Bool
    var apiKeyPreview: String?
    var explainModel: String
    var webSearchEnabled: Bool
    var supportsWebSearch: Bool
}

struct RuntimeProviderOptionDTO: Codable, Identifiable {
    var id: String
    var name: String
    var description: String
    var adapter: String
    var apiMode: String? = nil
    var protocolDriver: String? = nil
    var hermesPluginPath: String? = nil
    var exposureTier: String? = nil
    var defaultBaseURL: String
    var defaultModel: String
    var requiresApiKey: Bool
    var supportsModelListing: Bool
    var status: String
    var isAdvanced: Bool
    var configuredBaseURL: String? = nil
    var configuredModel: String? = nil
    var apiKeyConfigured: Bool? = nil
    var apiKeyPreview: String? = nil
}

struct RuntimeProviderCatalogDTO: Codable {
    var providers: [RuntimeProviderOptionDTO]
}

struct UpdateModelProviderSettingsRequest: Codable {
    var providerType: String
    var baseURL: String
    var apiKey: String?
    var explainModel: String
    var webSearchEnabled: Bool
}

struct WebProviderSettingsDTO: Codable {
    var providerType: String
    var apiKeyConfigured: Bool
    var apiKeyPreview: String?
    var webSearchEnabled: Bool
}

struct UpdateWebProviderSettingsRequest: Codable {
    var providerType: String
    var apiKey: String?
    var webSearchEnabled: Bool
}

struct WebProviderOptionDTO: Codable, Identifiable {
    var id: String
    var name: String
    var description: String
    var requiresApiKey: Bool
    var supportsSearch: Bool
    var supportsExtract: Bool
    var status: String
    var isDefault: Bool
    var apiKeyConfigured: Bool? = nil
    var apiKeyPreview: String? = nil
}

struct WebProviderCatalogDTO: Codable {
    var providers: [WebProviderOptionDTO]
}

struct ProviderModelDTO: Codable, Identifiable {
    var id: String
    var ownedBy: String
}

struct ProviderModelListDTO: Codable {
    var models: [ProviderModelDTO]
}

struct ConceptDTO: Codable, Identifiable {
    var id: UUID
    var canonicalTitle: String
    var displayTitle: String
    var oneLineExplanation: String
    var initialAnswer: String?
    var maturity: String
    var captureStatus: String
    var noteRevision: Int
    var blocks: [NoteBlockDTO]
    var tags: [String] = []
    var topics: [String] = []
    var answerSource: AnswerSourceDTO?
    var relations: [ConceptRelationDTO] = []
    var createdAt: Date?
    var updatedAt: Date?

    init(
        id: UUID,
        canonicalTitle: String,
        displayTitle: String,
        oneLineExplanation: String,
        initialAnswer: String? = nil,
        maturity: String,
        captureStatus: String,
        noteRevision: Int,
        blocks: [NoteBlockDTO],
        tags: [String] = [],
        topics: [String] = [],
        answerSource: AnswerSourceDTO? = nil,
        relations: [ConceptRelationDTO] = [],
        createdAt: Date? = nil,
        updatedAt: Date? = nil
    ) {
        self.id = id
        self.canonicalTitle = canonicalTitle
        self.displayTitle = displayTitle
        self.oneLineExplanation = oneLineExplanation
        self.initialAnswer = initialAnswer
        self.maturity = maturity
        self.captureStatus = captureStatus
        self.noteRevision = noteRevision
        self.blocks = blocks
        self.tags = tags
        self.topics = topics
        self.answerSource = answerSource
        self.relations = relations
        self.createdAt = createdAt
        self.updatedAt = updatedAt
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(UUID.self, forKey: .id)
        canonicalTitle = try container.decode(String.self, forKey: .canonicalTitle)
        displayTitle = try container.decode(String.self, forKey: .displayTitle)
        oneLineExplanation = try container.decode(String.self, forKey: .oneLineExplanation)
        initialAnswer = try container.decodeIfPresent(String.self, forKey: .initialAnswer)
        maturity = try container.decode(String.self, forKey: .maturity)
        captureStatus = try container.decode(String.self, forKey: .captureStatus)
        noteRevision = try container.decode(Int.self, forKey: .noteRevision)
        blocks = try container.decode([NoteBlockDTO].self, forKey: .blocks)
        tags = try container.decodeIfPresent([String].self, forKey: .tags) ?? []
        topics = try container.decodeIfPresent([String].self, forKey: .topics) ?? []
        answerSource = try container.decodeIfPresent(AnswerSourceDTO.self, forKey: .answerSource)
        relations = try container.decodeIfPresent([ConceptRelationDTO].self, forKey: .relations) ?? []
        createdAt = try container.decodeIfPresent(Date.self, forKey: .createdAt)
        updatedAt = try container.decodeIfPresent(Date.self, forKey: .updatedAt)
    }
}

struct BatchConceptRequest: Codable {
    var conceptIds: [UUID]
}

struct ConceptRelationDTO: Codable, Identifiable {
    var id: UUID
    var sourceConceptId: UUID
    var targetConceptId: UUID
    var relationType: String
    var status: String
    var confidence: Double
    var source: String
}

struct NoteBlockDTO: Codable, Identifiable, Hashable {
    var id: UUID
    var blockType: String
    var content: String
    var source: String
    var isUserLocked: Bool
    var position: Int? = nil
}

struct NoteRevisionSummaryDTO: Codable, Identifiable {
    var revision: Int
    var source: String
    var createdAt: Date
    var isCurrent: Bool
    var restoredFromRevision: Int?
    var id: Int { revision }
}

struct NoteRevisionDTO: Codable, Identifiable, Hashable {
    var revision: Int
    var source: String
    var createdAt: Date
    var isCurrent: Bool
    var restoredFromRevision: Int?
    var snapshotSchemaVersion: Int
    var displayTitle: String
    var canonicalTitle: String
    var oneLineExplanation: String
    var blocks: [NoteBlockDTO]
    var id: Int { revision }
}

struct UpdateConceptSummaryRequest: Codable {
    var displayTitle: String
    var oneLineExplanation: String
}

struct UpdateNoteBlockRequest: Codable {
    var content: String
}

struct UpdateConceptOrganizationRequest: Codable {
    var tags: [String]
    var topics: [String]
}

struct UpdateConceptNoteBlockRequest: Codable, Identifiable {
    var id: UUID?
    var blockType: String
    var content: String
}

struct UpdateConceptNoteRequest: Codable {
    var displayTitle: String
    var oneLineExplanation: String
    var blocks: [UpdateConceptNoteBlockRequest]
    var tags: [String]
    var topics: [String]
}

struct CreateConceptRelationRequest: Codable {
    var targetConceptId: UUID
    var relationType: String = "related"
}

struct ConceptTurnRequest: Codable {
    var question: String
    var replacingTurnIndex: Int? = nil
}

struct ConceptHistoryTurnDTO: Codable, Identifiable {
    var id = UUID()
    var role: String
    var content: String
    var answerSource: AnswerSourceDTO?
    var status: String? = "completed"

    enum CodingKeys: String, CodingKey {
        case role
        case content
        case answerSource
        case status
    }
}

struct ConceptTurnResponse: Codable {
    var answer: String
    var answerSource: AnswerSourceDTO
    var updateMode: String
    var concept: ConceptDTO
    var proposal: UpdateProposalDTO?
}

struct ConceptTurnStreamEvent: Codable {
    var type: String
    var delta: String?
    var response: ConceptTurnResponse?
    var modelRun: ModelRunDTO? = nil
    var sequence: Int? = nil
    var progressLabel: String? = nil
}

struct ConceptInitialStreamEvent: Codable {
    var type: String
    var delta: String?
    var concept: ConceptDTO?
    var modelRun: ModelRunDTO? = nil
    var sequence: Int? = nil
    var progressLabel: String? = nil
}

struct UpdateProposalDTO: Codable, Identifiable {
    var id: UUID
    var baseNoteRevision: Int
    var patchOperations: [PatchOperationDTO]
    var rationale: String
    var confidence: Double
    var status: String
    var origin: String? = nil
    var sourceRunId: UUID? = nil
}

struct PatchOperationDTO: Codable, Identifiable {
    var id = UUID()
    var operation: String
    var targetBlockId: UUID?
    var content: String?
    var oldValueHash: String?
    var newContent: String?
    var targetConceptId: UUID?
    var relationType: String?

    enum CodingKeys: String, CodingKey {
        case operation
        case targetBlockId
        case content
        case oldValueHash
        case newContent
        case targetConceptId
        case relationType
    }
}

struct AnswerSourceDTO: Codable {
    var sourceType: String
    var confidence: Double
    var uncertaintyNote: String?
    var retrievalUsed: Bool? = nil
    var freshnessNote: String? = nil
    var citations: [CitationDTO]? = nil
}

struct CitationDTO: Codable, Identifiable {
    var id: String { url }
    var sourceId: String?
    var title: String
    var url: String
}
