import Foundation

/// Single source of truth for the local-vs-backend topic ownership boundary.
///
/// ```
/// Card metadata      = backend-managed tags + topics
/// Library categories = device-local organization only
///                      = never uploaded
///                      = never overwritten by backend
///                      = never deleted by card refresh / full-note save
/// ```
///
/// Library categories are marked with `source == "category"` on BOTH the
/// `Topic` and each of its `ConceptTopic` assignments. Every other topic is
/// backend-managed card metadata. A category and a card topic may share a name;
/// they remain separate `Topic` entities and never reuse each other's `source`.
enum LibraryCategoryOwnership {
    /// `source` value marking a `Topic` / `ConceptTopic` as a local Library category.
    static let categorySource = "category"

    static func isCategory(source: String) -> Bool { source == categorySource }
    static func isCategory(_ topic: Topic) -> Bool { isCategory(source: topic.source) }
    static func isCategory(_ assignment: ConceptTopic) -> Bool { isCategory(source: assignment.source) }

    /// Backend-managed (card) assignments — the ONLY assignments remote sync /
    /// note save may delete or replace. Local categories are excluded.
    static func cardAssignments(_ assignments: [ConceptTopic]) -> [ConceptTopic] {
        assignments.filter { !isCategory($0) }
    }

    /// Local Library category assignments — never uploaded, never replaced by sync.
    static func categoryAssignments(_ assignments: [ConceptTopic]) -> [ConceptTopic] {
        assignments.filter { isCategory($0) }
    }
}

/// Projects a concept's topics into the contexts that must stay isolated:
/// card metadata (outbound sync / note payload / card display) vs local Library
/// categories (Library filtering / display).
///
/// A topic counts for a context only when BOTH its assignment and its `Topic`
/// agree on category-ness, so a polluted assignment can never leak a local
/// category into the card-topic projection (or vice-versa).
///
/// **Codex full-note editor / outbound note payload must use
/// `cardTopicNames(...)` as the topics field** — never the raw assignment list —
/// so local Library categories are never uploaded.
enum CardTopicProjection {
    /// Card-metadata topic names for a concept — for outbound sync / note
    /// payload and card display. Local categories are never included.
    static func cardTopicNames(
        conceptId: UUID,
        assignments: [ConceptTopic],
        topics: [Topic]
    ) -> [String] {
        names(conceptId: conceptId, assignments: assignments, topics: topics, wantCategory: false)
    }

    /// Local Library category names for a concept — for Library filtering / display.
    static func categoryNames(
        conceptId: UUID,
        assignments: [ConceptTopic],
        topics: [Topic]
    ) -> [String] {
        names(conceptId: conceptId, assignments: assignments, topics: topics, wantCategory: true)
    }

    private static func names(
        conceptId: UUID,
        assignments: [ConceptTopic],
        topics: [Topic],
        wantCategory: Bool
    ) -> [String] {
        let topicsById = Dictionary(topics.map { ($0.id, $0) }, uniquingKeysWith: { first, _ in first })
        let matched = assignments.compactMap { assignment -> String? in
            guard assignment.conceptId == conceptId,
                  LibraryCategoryOwnership.isCategory(assignment) == wantCategory,
                  let topic = topicsById[assignment.topicId],
                  LibraryCategoryOwnership.isCategory(topic) == wantCategory else {
                return nil
            }
            return topic.name
        }
        // De-duplicate case-insensitively, then sort for stable display.
        var seen = Set<String>()
        return matched
            .filter { seen.insert($0.lowercased()).inserted }
            .sorted { $0.localizedCaseInsensitiveCompare($1) == .orderedAscending }
    }
}
