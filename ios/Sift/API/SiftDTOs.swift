import Foundation

struct CreateConceptRequest: Codable {
    var rawCapture: String
    var locale: String
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
    var maturity: String
    var captureStatus: String
    var noteRevision: Int
    var blocks: [NoteBlockDTO]
    var tags: [String] = []
    var topics: [String] = []
    var answerSource: AnswerSourceDTO?
    var relations: [ConceptRelationDTO] = []

    init(
        id: UUID,
        canonicalTitle: String,
        displayTitle: String,
        oneLineExplanation: String,
        maturity: String,
        captureStatus: String,
        noteRevision: Int,
        blocks: [NoteBlockDTO],
        tags: [String] = [],
        topics: [String] = [],
        answerSource: AnswerSourceDTO? = nil,
        relations: [ConceptRelationDTO] = []
    ) {
        self.id = id
        self.canonicalTitle = canonicalTitle
        self.displayTitle = displayTitle
        self.oneLineExplanation = oneLineExplanation
        self.maturity = maturity
        self.captureStatus = captureStatus
        self.noteRevision = noteRevision
        self.blocks = blocks
        self.tags = tags
        self.topics = topics
        self.answerSource = answerSource
        self.relations = relations
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(UUID.self, forKey: .id)
        canonicalTitle = try container.decode(String.self, forKey: .canonicalTitle)
        displayTitle = try container.decode(String.self, forKey: .displayTitle)
        oneLineExplanation = try container.decode(String.self, forKey: .oneLineExplanation)
        maturity = try container.decode(String.self, forKey: .maturity)
        captureStatus = try container.decode(String.self, forKey: .captureStatus)
        noteRevision = try container.decode(Int.self, forKey: .noteRevision)
        blocks = try container.decode([NoteBlockDTO].self, forKey: .blocks)
        tags = try container.decodeIfPresent([String].self, forKey: .tags) ?? []
        topics = try container.decodeIfPresent([String].self, forKey: .topics) ?? []
        answerSource = try container.decodeIfPresent(AnswerSourceDTO.self, forKey: .answerSource)
        relations = try container.decodeIfPresent([ConceptRelationDTO].self, forKey: .relations) ?? []
    }
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

struct NoteBlockDTO: Codable, Identifiable {
    var id: UUID
    var blockType: String
    var content: String
    var source: String
    var isUserLocked: Bool
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

struct CreateConceptRelationRequest: Codable {
    var targetConceptId: UUID
    var relationType: String = "related"
}

struct ConceptTurnRequest: Codable {
    var question: String
}

struct ConceptHistoryTurnDTO: Codable, Identifiable {
    var id = UUID()
    var role: String
    var content: String
    var answerSource: AnswerSourceDTO?

    enum CodingKeys: String, CodingKey {
        case role
        case content
        case answerSource
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
}

struct UpdateProposalDTO: Codable, Identifiable {
    var id: UUID
    var baseNoteRevision: Int
    var patchOperations: [PatchOperationDTO]
    var rationale: String
    var confidence: Double
    var status: String
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
