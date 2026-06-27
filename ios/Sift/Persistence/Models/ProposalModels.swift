import Foundation
import SwiftData

@Model
final class ConceptUpdateProposal {
    @Attribute(.unique) var id: UUID
    var conceptId: UUID
    var sourceMessageId: UUID
    var baseNoteRevision: Int
    var patchOperationsJSON: String
    var rationale: String
    var confidence: Double
    var status: String
    var mergeIdempotencyKey: String?
    var mergeOperationStatus: String?
    var createdAt: Date
    var resolvedAt: Date?

    init(
        id: UUID = UUID(),
        conceptId: UUID,
        sourceMessageId: UUID,
        baseNoteRevision: Int,
        patchOperationsJSON: String,
        rationale: String,
        confidence: Double,
        status: String = ProposalStatus.proposed.rawValue,
        mergeIdempotencyKey: String? = nil,
        mergeOperationStatus: String? = nil,
        createdAt: Date = .now,
        resolvedAt: Date? = nil
    ) {
        self.id = id
        self.conceptId = conceptId
        self.sourceMessageId = sourceMessageId
        self.baseNoteRevision = baseNoteRevision
        self.patchOperationsJSON = patchOperationsJSON
        self.rationale = rationale
        self.confidence = confidence
        self.status = status
        self.mergeIdempotencyKey = mergeIdempotencyKey
        self.mergeOperationStatus = mergeOperationStatus
        self.createdAt = createdAt
        self.resolvedAt = resolvedAt
    }
}

enum ProposalStatus: String, Codable, CaseIterable {
    case proposed
    case accepted
    case dismissed
    case stale
}

@Model
final class AnswerSource {
    @Attribute(.unique) var id: UUID
    var sourceType: String
    var citationsJSON: String
    var verifiedAt: Date?
    var confidence: Double
    var uncertaintyNote: String

    init(
        id: UUID = UUID(),
        sourceType: String = AnswerSourceType.modelKnowledge.rawValue,
        citationsJSON: String = "[]",
        verifiedAt: Date? = nil,
        confidence: Double = 0.5,
        uncertaintyNote: String = ""
    ) {
        self.id = id
        self.sourceType = sourceType
        self.citationsJSON = citationsJSON
        self.verifiedAt = verifiedAt
        self.confidence = confidence
        self.uncertaintyNote = uncertaintyNote
    }
}

enum AnswerSourceType: String, Codable, CaseIterable {
    case modelKnowledge
    case userProvided
    case searchDiscovered
    case sourceRead
    case sourceVerified
    case webVerified
}
