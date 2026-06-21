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

