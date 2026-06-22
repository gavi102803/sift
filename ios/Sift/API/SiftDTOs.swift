import Foundation

struct CreateConceptRequest: Codable {
    var rawCapture: String
    var locale: String
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
}

struct NoteBlockDTO: Codable, Identifiable {
    var id: UUID
    var blockType: String
    var content: String
    var source: String
    var isUserLocked: Bool
}

struct ConceptTurnRequest: Codable {
    var question: String
}

struct ConceptHistoryTurnDTO: Codable, Identifiable {
    var id = UUID()
    var role: String
    var content: String

    enum CodingKeys: String, CodingKey {
        case role
        case content
    }
}

struct ConceptTurnResponse: Codable {
    var answer: String
    var answerSource: AnswerSourceDTO
    var updateMode: String
    var concept: ConceptDTO
    var proposal: UpdateProposalDTO?
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
}
