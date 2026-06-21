import Foundation
import SwiftData

@Model
final class NoteRevision {
    @Attribute(.unique) var id: UUID
    var conceptId: UUID
    var revision: Int
    var snapshotJSON: String
    var sourceMessageId: UUID?
    var mergeMode: String
    var createdAt: Date

    init(
        id: UUID = UUID(),
        conceptId: UUID,
        revision: Int,
        snapshotJSON: String,
        sourceMessageId: UUID? = nil,
        mergeMode: String,
        createdAt: Date = .now
    ) {
        self.id = id
        self.conceptId = conceptId
        self.revision = revision
        self.snapshotJSON = snapshotJSON
        self.sourceMessageId = sourceMessageId
        self.mergeMode = mergeMode
        self.createdAt = createdAt
    }
}

@Model
final class UpdateEvent {
    @Attribute(.unique) var id: UUID
    var conceptId: UUID
    var noteRevision: Int
    var sourceMessageId: UUID?
    var proposalId: UUID?
    var eventType: String
    var actor: String
    var createdAt: Date

    init(
        id: UUID = UUID(),
        conceptId: UUID,
        noteRevision: Int,
        sourceMessageId: UUID? = nil,
        proposalId: UUID? = nil,
        eventType: String,
        actor: String,
        createdAt: Date = .now
    ) {
        self.id = id
        self.conceptId = conceptId
        self.noteRevision = noteRevision
        self.sourceMessageId = sourceMessageId
        self.proposalId = proposalId
        self.eventType = eventType
        self.actor = actor
        self.createdAt = createdAt
    }
}

enum UpdateEventType: String, Codable, CaseIterable {
    case manualEdit
    case autoMerge
    case confirmedMerge
    case dismissedProposal
    case retryGeneration
}

enum UpdateActor: String, Codable, CaseIterable {
    case user
    case system
    case ai
}

