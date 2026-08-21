import Foundation
import SwiftData

@Model
final class Concept {
    @Attribute(.unique) var id: UUID
    var canonicalTitle: String
    var displayTitle: String
    var aliasesText: String
    var language: String
    var oneLineExplanation: String
    var maturity: String
    var captureStatus: String
    var noteRevision: Int
    var answerSourceJSON: String?
    var captureGenerationIdempotencyKey: String?
    var captureGenerationOperationStatus: String?
    var createdAt: Date
    var updatedAt: Date
    var lastViewedAt: Date?

    @Relationship(deleteRule: .cascade, inverse: \ConceptNote.concept)
    var note: ConceptNote?

    @Relationship(deleteRule: .cascade, inverse: \Conversation.concept)
    var conversation: Conversation?

    init(
        id: UUID = UUID(),
        canonicalTitle: String,
        displayTitle: String? = nil,
        aliasesText: String = "",
        language: String = "en",
        oneLineExplanation: String = "",
        maturity: String = ConceptMaturity.initial.rawValue,
        captureStatus: String = CaptureStatus.draft.rawValue,
        noteRevision: Int = 0,
        answerSourceJSON: String? = nil,
        captureGenerationIdempotencyKey: String? = nil,
        captureGenerationOperationStatus: String? = nil,
        createdAt: Date = .now,
        updatedAt: Date = .now,
        lastViewedAt: Date? = nil
    ) {
        self.id = id
        self.canonicalTitle = canonicalTitle
        self.displayTitle = displayTitle ?? canonicalTitle
        self.aliasesText = aliasesText
        self.language = language
        self.oneLineExplanation = oneLineExplanation
        self.maturity = maturity
        self.captureStatus = captureStatus
        self.noteRevision = noteRevision
        self.answerSourceJSON = answerSourceJSON
        self.captureGenerationIdempotencyKey = captureGenerationIdempotencyKey
        self.captureGenerationOperationStatus = captureGenerationOperationStatus
        self.createdAt = createdAt
        self.updatedAt = updatedAt
        self.lastViewedAt = lastViewedAt
    }
}

enum LocalOperationStatus: String, Codable, CaseIterable {
    case pending
    case inFlight
    case failed
    case completed
}

enum CaptureStatus: String, Codable, CaseIterable {
    case draft
    case pendingGeneration
    case generating
    case buildingCard
    case needsDisambiguation
    case ready
    case generationFailed
    case archived
}

enum ConceptMaturity: String, Codable, CaseIterable {
    case initial
    case growing
    case mature
}

@Model
final class ConceptNote {
    @Attribute(.unique) var id: UUID
    var revision: Int
    var updatedAt: Date
    var updatedBy: String

    var concept: Concept?

    @Relationship(deleteRule: .cascade, inverse: \NoteBlock.note)
    var blocks: [NoteBlock]

    init(
        id: UUID = UUID(),
        revision: Int = 0,
        updatedAt: Date = .now,
        updatedBy: String = "system",
        concept: Concept? = nil,
        blocks: [NoteBlock] = []
    ) {
        self.id = id
        self.revision = revision
        self.updatedAt = updatedAt
        self.updatedBy = updatedBy
        self.concept = concept
        self.blocks = blocks
    }
}

@Model
final class NoteBlock {
    @Attribute(.unique) var id: UUID
    var blockType: String
    var content: String
    var source: String
    var isUserLocked: Bool
    var lastEditedBy: String
    var position: Int?
    var updatedAt: Date

    var note: ConceptNote?

    init(
        id: UUID = UUID(),
        blockType: String,
        content: String = "",
        source: String = NoteBlockSource.ai.rawValue,
        isUserLocked: Bool = false,
        lastEditedBy: String = "ai",
        position: Int? = nil,
        updatedAt: Date = .now,
        note: ConceptNote? = nil
    ) {
        self.id = id
        self.blockType = blockType
        self.content = content
        self.source = source
        self.isUserLocked = isUserLocked
        self.lastEditedBy = lastEditedBy
        self.position = position
        self.updatedAt = updatedAt
        self.note = note
    }
}

enum NoteBlockType: String, Codable, CaseIterable {
    case oneLineDefinition
    case whatItIs
    case whyItMatters
    case example
    case distinction
    case misconception
    case userContext
    case openQuestion
    case relatedConcepts
    case caveat
    case commonMisunderstandings
    case relatedConceptsDisplay
    case userTakeaways
}

enum NoteBlockSource: String, Codable, CaseIterable {
    case ai
    case user
    case merged
}
