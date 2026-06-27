import Foundation
import SwiftData

@Model
final class Conversation {
    @Attribute(.unique) var id: UUID
    var initialQuery: String
    var cardMemory: String
    var memoryRevision: Int
    var memoryUpdatedAt: Date
    var defaultModelId: String
    var pendingFollowUpIdempotencyKey: String?
    var pendingFollowUpQuestion: String?
    var pendingFollowUpOperationStatus: String?
    var createdAt: Date
    var updatedAt: Date

    var concept: Concept?

    @Relationship(deleteRule: .cascade, inverse: \ConversationMessage.conversation)
    var messages: [ConversationMessage]

    init(
        id: UUID = UUID(),
        initialQuery: String,
        cardMemory: String = "",
        memoryRevision: Int = 0,
        memoryUpdatedAt: Date = .now,
        defaultModelId: String = "sift-explain",
        pendingFollowUpIdempotencyKey: String? = nil,
        pendingFollowUpQuestion: String? = nil,
        pendingFollowUpOperationStatus: String? = nil,
        createdAt: Date = .now,
        updatedAt: Date = .now,
        concept: Concept? = nil,
        messages: [ConversationMessage] = []
    ) {
        self.id = id
        self.initialQuery = initialQuery
        self.cardMemory = cardMemory
        self.memoryRevision = memoryRevision
        self.memoryUpdatedAt = memoryUpdatedAt
        self.defaultModelId = defaultModelId
        self.pendingFollowUpIdempotencyKey = pendingFollowUpIdempotencyKey
        self.pendingFollowUpQuestion = pendingFollowUpQuestion
        self.pendingFollowUpOperationStatus = pendingFollowUpOperationStatus
        self.createdAt = createdAt
        self.updatedAt = updatedAt
        self.concept = concept
        self.messages = messages
    }
}

@Model
final class ModelThread {
    @Attribute(.unique) var id: UUID
    var conversationId: UUID
    var providerId: String
    var modelId: String
    var remoteThreadId: String?
    var lastUsedAt: Date

    init(
        id: UUID = UUID(),
        conversationId: UUID,
        providerId: String,
        modelId: String,
        remoteThreadId: String? = nil,
        lastUsedAt: Date = .now
    ) {
        self.id = id
        self.conversationId = conversationId
        self.providerId = providerId
        self.modelId = modelId
        self.remoteThreadId = remoteThreadId
        self.lastUsedAt = lastUsedAt
    }
}

@Model
final class ConversationMessage {
    @Attribute(.unique) var id: UUID
    var role: String
    var content: String
    var modelId: String?
    var providerId: String?
    var createdAt: Date
    var mergedIntoNote: Bool
    var updateMode: String
    var answerSourceId: UUID?
    var operationIdempotencyKey: String?
    var operationStatus: String?

    var conversation: Conversation?

    init(
        id: UUID = UUID(),
        role: String,
        content: String,
        modelId: String? = nil,
        providerId: String? = nil,
        createdAt: Date = .now,
        mergedIntoNote: Bool = false,
        updateMode: String = UpdateMode.none.rawValue,
        answerSourceId: UUID? = nil,
        operationIdempotencyKey: String? = nil,
        operationStatus: String? = nil,
        conversation: Conversation? = nil
    ) {
        self.id = id
        self.role = role
        self.content = content
        self.modelId = modelId
        self.providerId = providerId
        self.createdAt = createdAt
        self.mergedIntoNote = mergedIntoNote
        self.updateMode = updateMode
        self.answerSourceId = answerSourceId
        self.operationIdempotencyKey = operationIdempotencyKey
        self.operationStatus = operationStatus
        self.conversation = conversation
    }
}

enum ConversationRole: String, Codable, CaseIterable {
    case user
    case assistant
    case system
}

enum UpdateMode: String, Codable, CaseIterable {
    case none
    case autoMerge
    case needsConfirmation
}

/// Internal `ConversationMessage.updateMode` sentinels used to tag locally
/// recorded messages that are not part of the normal merge flow. Single source
/// of truth shared by the local store (which writes them) and the UI (which
/// reconciles them) so neither side hardcodes the raw strings.
enum LocalConversationMarker {
    /// The original capture question and its first generated answer.
    static let initialCapture = "initialCapture"
    /// A follow-up the user wrote that failed to send, or a generation failure
    /// notice. Never rendered as a real conversation turn.
    static let failed = "failed"
}
