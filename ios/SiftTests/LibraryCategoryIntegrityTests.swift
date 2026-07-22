import SwiftData
import XCTest
@testable import Sift

/// Real-`ModelContainer` reload regression tests for the local Library category
/// ownership boundary. Each test writes through a `ConceptLocalStore`, saves,
/// then re-reads from a *fresh* `ModelContext` on the same container to prove the
/// data survives a reload — not just an in-memory array.
@MainActor
final class LibraryCategoryIntegrityTests: XCTestCase {
    private let conceptId = UUID()

    // MARK: - Cases

    /// 1. A local category survives a remote topic refresh that changes topics.
    func testCategorySurvivesRemoteTopicRefresh() throws {
        let container = try makeContainer()
        try seedConcept(topics: ["AI", "RAG"], in: container)
        assignCategory("Machine Learning", in: container)
        try save(container)

        try upsert(topics: ["AI", "Vectors"], in: container)   // refresh
        try save(container)

        let reloaded = ModelContext(container)
        XCTAssertEqual(categoryNames(reloaded), ["Machine Learning"])
        XCTAssertEqual(cardTopicNames(reloaded), ["AI", "Vectors"])
    }

    /// 2. Removing a remote topic does not remove the local category.
    func testCategoryNotRemovedWhenRemoteTopicRemoved() throws {
        let container = try makeContainer()
        try seedConcept(topics: ["AI"], in: container)
        assignCategory("ML", in: container)
        try save(container)

        try upsert(topics: [], in: container)   // backend dropped all topics
        try save(container)

        let reloaded = ModelContext(container)
        XCTAssertTrue(cardTopicNames(reloaded).isEmpty)
        XCTAssertEqual(categoryNames(reloaded), ["ML"])
    }

    /// 3. A full-note-style concept upsert preserves local categories.
    func testCategorySurvivesFullNoteUpsert() throws {
        let container = try makeContainer()
        try seedConcept(topics: ["Databases"], in: container)
        assignCategory("Systems", in: container)
        try save(container)

        // A PUT /note response is applied through upsertConcept just like refresh.
        try upsert(topics: ["Databases", "Transactions"], in: container)
        try save(container)

        let reloaded = ModelContext(container)
        XCTAssertEqual(categoryNames(reloaded), ["Systems"])
        XCTAssertEqual(cardTopicNames(reloaded), ["Databases", "Transactions"])
    }

    /// 4. A same-named category and card topic stay isolated (separate Topic
    ///    entities, distinct sources, no shared assignment).
    func testSameNameCategoryAndCardTopicStayIsolated() throws {
        let container = try makeContainer()
        assignCategory("AI", in: container)
        try seedConcept(topics: ["AI"], in: container)   // card topic same name
        try save(container)

        let reloaded = ModelContext(container)
        let topics = try reloaded.fetch(FetchDescriptor<Topic>()).filter { $0.name == "AI" }
        XCTAssertEqual(topics.count, 2, "category + card topic must be separate Topic entities")
        XCTAssertEqual(Set(topics.map(\.source)), [LibraryCategoryOwnership.categorySource, UpdateActor.user.rawValue])

        let assignments = try reloaded.fetch(FetchDescriptor<ConceptTopic>()).filter { $0.conceptId == conceptId }
        XCTAssertEqual(LibraryCategoryOwnership.categoryAssignments(assignments).count, 1)
        XCTAssertEqual(LibraryCategoryOwnership.cardAssignments(assignments).count, 1)
        // The two assignments point at different Topic entities.
        let categoryTopicId = LibraryCategoryOwnership.categoryAssignments(assignments).first?.topicId
        let cardTopicId = LibraryCategoryOwnership.cardAssignments(assignments).first?.topicId
        XCTAssertNotEqual(categoryTopicId, cardTopicId)

        XCTAssertEqual(cardTopicNames(reloaded), ["AI"])
        XCTAssertEqual(categoryNames(reloaded), ["AI"])
    }

    /// 5. A category assignment persists across a SwiftData reload.
    func testCategoryAssignmentPersistsAcrossReload() throws {
        let container = try makeContainer()
        try seedConcept(topics: [], in: container)
        assignCategory("Reading List", in: container)
        try save(container)

        let reloaded = ModelContext(container)
        let assignments = try reloaded.fetch(FetchDescriptor<ConceptTopic>()).filter { $0.conceptId == conceptId }
        XCTAssertEqual(LibraryCategoryOwnership.categoryAssignments(assignments).count, 1)
    }

    /// 6. A category-only topic never appears in the card-topic projection.
    func testCategoryOnlyTopicNotInCardProjection() throws {
        let container = try makeContainer()
        try seedConcept(topics: [], in: container)
        assignCategory("ML", in: container)
        try save(container)

        let reloaded = ModelContext(container)
        XCTAssertTrue(cardTopicNames(reloaded).isEmpty)
        XCTAssertEqual(categoryNames(reloaded), ["ML"])
    }

    /// 7. Computing the card-topic projection neither deletes nor includes the
    ///    Library category.
    func testCardProjectionDoesNotTouchCategory() throws {
        let container = try makeContainer()
        try seedConcept(topics: ["AI"], in: container)
        assignCategory("ML", in: container)
        try save(container)

        let reloaded = ModelContext(container)
        XCTAssertEqual(cardTopicNames(reloaded), ["AI"])   // category excluded
        // Reading the projection didn't delete the category assignment.
        let assignments = try reloaded.fetch(FetchDescriptor<ConceptTopic>()).filter { $0.conceptId == conceptId }
        XCTAssertEqual(LibraryCategoryOwnership.categoryAssignments(assignments).count, 1)
    }

    /// 8. Repeated refresh / upsert never duplicates the category assignment.
    func testRepeatedUpsertDoesNotDuplicateCategory() throws {
        let container = try makeContainer()
        try seedConcept(topics: ["AI"], in: container)
        assignCategory("ML", in: container)
        try save(container)

        for topics in [["AI", "RAG"], ["AI"], ["Vectors"]] {
            try upsert(topics: topics, in: container)
            try save(container)
        }

        let reloaded = ModelContext(container)
        let assignments = try reloaded.fetch(FetchDescriptor<ConceptTopic>()).filter { $0.conceptId == conceptId }
        XCTAssertEqual(LibraryCategoryOwnership.categoryAssignments(assignments).count, 1)
        // Card topics also aren't duplicated.
        XCTAssertEqual(cardTopicNames(reloaded), ["Vectors"])
    }

    /// 9. After a refresh, the Library filter still finds the card in its category.
    func testLibraryFilterStillFindsCardInCategory() throws {
        let container = try makeContainer()
        try seedConcept(topics: ["AI"], in: container)
        let category = assignCategory("ML", in: container)
        try save(container)

        try upsert(topics: ["AI", "RAG"], in: container)
        try save(container)

        let reloaded = ModelContext(container)
        // Mirror ConceptLibraryView.selectedCategoryAssignments + membership.
        let assignments = try reloaded.fetch(FetchDescriptor<ConceptTopic>())
            .filter { $0.topicId == category.id && LibraryCategoryOwnership.isCategory($0) }
        XCTAssertTrue(assignments.contains { $0.conceptId == conceptId })
    }

    // MARK: - Helpers

    private func makeContainer() throws -> ModelContainer {
        let schema = Schema([
            Concept.self, ConceptNote.self, NoteBlock.self, NoteRevision.self,
            UpdateEvent.self, Conversation.self, ModelThread.self, ConversationMessage.self,
            ModelRunMirror.self, ConceptUpdateProposal.self, AnswerSource.self, Tag.self, ConceptTag.self,
            Topic.self, ConceptTopic.self, ConceptRelation.self
        ])
        return try ModelContainer(
            for: schema,
            configurations: [ModelConfiguration(schema: schema, isStoredInMemoryOnly: true)]
        )
    }

    private func dto(topics: [String]) -> ConceptDTO {
        ConceptDTO(
            id: conceptId,
            canonicalTitle: "RAG",
            displayTitle: "RAG",
            oneLineExplanation: "",
            maturity: ConceptMaturity.growing.rawValue,
            captureStatus: CaptureStatus.ready.rawValue,
            noteRevision: 1,
            blocks: [],
            tags: [],
            topics: topics
        )
    }

    private func seedConcept(topics: [String], in container: ModelContainer) throws {
        _ = try ConceptLocalStore(modelContext: container.mainContext).upsertConcept(from: dto(topics: topics))
    }

    private func upsert(topics: [String], in container: ModelContainer) throws {
        _ = try ConceptLocalStore(modelContext: container.mainContext).upsertConcept(from: dto(topics: topics))
    }

    @discardableResult
    private func assignCategory(_ name: String, in container: ModelContainer) -> Topic {
        // Mirror ConceptLibraryView's local category creation + assignment.
        let context = container.mainContext
        let topic = Topic(name: name, source: LibraryCategoryOwnership.categorySource)
        context.insert(topic)
        context.insert(ConceptTopic(conceptId: conceptId, topicId: topic.id, source: LibraryCategoryOwnership.categorySource))
        return topic
    }

    private func save(_ container: ModelContainer) throws {
        try container.mainContext.save()
    }

    private func cardTopicNames(_ context: ModelContext) -> [String] {
        let assignments = (try? context.fetch(FetchDescriptor<ConceptTopic>())) ?? []
        let topics = (try? context.fetch(FetchDescriptor<Topic>())) ?? []
        return CardTopicProjection.cardTopicNames(conceptId: conceptId, assignments: assignments, topics: topics)
    }

    private func categoryNames(_ context: ModelContext) -> [String] {
        let assignments = (try? context.fetch(FetchDescriptor<ConceptTopic>())) ?? []
        let topics = (try? context.fetch(FetchDescriptor<Topic>())) ?? []
        return CardTopicProjection.categoryNames(conceptId: conceptId, assignments: assignments, topics: topics)
    }
}
