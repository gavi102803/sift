import SwiftData
import XCTest
@testable import Sift

/// Isolated (no store) tests for the ownership policy + projection helper.
final class LibraryCategoryOwnershipTests: XCTestCase {
    private let conceptId = UUID()
    private let cardTopicId = UUID()
    private let categoryTopicId = UUID()

    func testIsCategoryRecognisesTheMarker() {
        XCTAssertTrue(LibraryCategoryOwnership.isCategory(source: "category"))
        XCTAssertFalse(LibraryCategoryOwnership.isCategory(source: "user"))
        XCTAssertFalse(LibraryCategoryOwnership.isCategory(source: "ai"))
    }

    func testSplitsCardAndCategoryAssignments() {
        let assignments = [
            ConceptTopic(conceptId: conceptId, topicId: cardTopicId, source: "user"),
            ConceptTopic(conceptId: conceptId, topicId: categoryTopicId, source: "category")
        ]
        XCTAssertEqual(LibraryCategoryOwnership.cardAssignments(assignments).map(\.topicId), [cardTopicId])
        XCTAssertEqual(LibraryCategoryOwnership.categoryAssignments(assignments).map(\.topicId), [categoryTopicId])
    }

    /// Same-named category + card topic stay isolated across the two projections.
    func testCardProjectionExcludesCategoriesAndViceVersa() {
        let topics = [
            Topic(id: cardTopicId, name: "AI", source: "user"),
            Topic(id: categoryTopicId, name: "AI", source: "category")
        ]
        let assignments = [
            ConceptTopic(conceptId: conceptId, topicId: cardTopicId, source: "user"),
            ConceptTopic(conceptId: conceptId, topicId: categoryTopicId, source: "category")
        ]
        XCTAssertEqual(
            CardTopicProjection.cardTopicNames(conceptId: conceptId, assignments: assignments, topics: topics),
            ["AI"]
        )
        XCTAssertEqual(
            CardTopicProjection.categoryNames(conceptId: conceptId, assignments: assignments, topics: topics),
            ["AI"]
        )
        // Card projection must not include the category Topic's id, and vice-versa.
        XCTAssertEqual(CardTopicProjection.cardTopicNames(conceptId: conceptId, assignments: assignments, topics: topics).count, 1)
    }

    /// A polluted assignment (card-source assignment pointing at a category Topic)
    /// leaks into neither projection.
    func testPollutedAssignmentLeaksIntoNeitherProjection() {
        let topics = [Topic(id: categoryTopicId, name: "AI", source: "category")]
        let polluted = [ConceptTopic(conceptId: conceptId, topicId: categoryTopicId, source: "user")]
        XCTAssertTrue(CardTopicProjection.cardTopicNames(conceptId: conceptId, assignments: polluted, topics: topics).isEmpty)
        XCTAssertTrue(CardTopicProjection.categoryNames(conceptId: conceptId, assignments: polluted, topics: topics).isEmpty)
    }

    func testProjectionScopesToConceptAndDeduplicates() {
        let other = UUID()
        let dupId = UUID()
        let topics = [
            Topic(id: cardTopicId, name: "RAG", source: "user"),
            Topic(id: dupId, name: "rag", source: "user"),
            Topic(id: other, name: "Other", source: "user")
        ]
        let assignments = [
            ConceptTopic(conceptId: conceptId, topicId: cardTopicId, source: "user"),
            ConceptTopic(conceptId: conceptId, topicId: dupId, source: "user"),
            ConceptTopic(conceptId: UUID(), topicId: other, source: "user")
        ]
        // Case-insensitive de-dup; the other concept's topic is excluded.
        XCTAssertEqual(
            CardTopicProjection.cardTopicNames(conceptId: conceptId, assignments: assignments, topics: topics),
            ["RAG"]
        )
    }
}
