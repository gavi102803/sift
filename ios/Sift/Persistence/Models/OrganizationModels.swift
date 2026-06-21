import Foundation
import SwiftData

@Model
final class Tag {
    @Attribute(.unique) var id: UUID
    var name: String
    var source: String
    var createdAt: Date

    init(id: UUID = UUID(), name: String, source: String = "ai", createdAt: Date = .now) {
        self.id = id
        self.name = name
        self.source = source
        self.createdAt = createdAt
    }
}

@Model
final class ConceptTag {
    @Attribute(.unique) var id: UUID
    var conceptId: UUID
    var tagId: UUID
    var confidence: Double
    var source: String

    init(
        id: UUID = UUID(),
        conceptId: UUID,
        tagId: UUID,
        confidence: Double = 1,
        source: String = "ai"
    ) {
        self.id = id
        self.conceptId = conceptId
        self.tagId = tagId
        self.confidence = confidence
        self.source = source
    }
}

@Model
final class Topic {
    @Attribute(.unique) var id: UUID
    var name: String
    var source: String
    var createdAt: Date

    init(id: UUID = UUID(), name: String, source: String = "ai", createdAt: Date = .now) {
        self.id = id
        self.name = name
        self.source = source
        self.createdAt = createdAt
    }
}

@Model
final class ConceptTopic {
    @Attribute(.unique) var id: UUID
    var conceptId: UUID
    var topicId: UUID
    var confidence: Double
    var source: String

    init(
        id: UUID = UUID(),
        conceptId: UUID,
        topicId: UUID,
        confidence: Double = 1,
        source: String = "ai"
    ) {
        self.id = id
        self.conceptId = conceptId
        self.topicId = topicId
        self.confidence = confidence
        self.source = source
    }
}

@Model
final class ConceptRelation {
    @Attribute(.unique) var id: UUID
    var sourceConceptId: UUID
    var targetConceptId: UUID
    var relationType: String
    var status: String
    var confidence: Double
    var source: String
    var createdAt: Date

    init(
        id: UUID = UUID(),
        sourceConceptId: UUID,
        targetConceptId: UUID,
        relationType: String,
        status: String = "proposed",
        confidence: Double = 1,
        source: String = "ai",
        createdAt: Date = .now
    ) {
        self.id = id
        self.sourceConceptId = sourceConceptId
        self.targetConceptId = targetConceptId
        self.relationType = relationType
        self.status = status
        self.confidence = confidence
        self.source = source
        self.createdAt = createdAt
    }
}

