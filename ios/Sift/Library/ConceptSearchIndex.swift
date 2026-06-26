import Foundation

enum ConceptSearchIndex {
    static func matches(
        query rawQuery: String,
        concept: Concept,
        tags: [String],
        topics: [String]
    ) -> Bool {
        let query = rawQuery.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !query.isEmpty else { return true }

        return concept.displayTitle.localizedCaseInsensitiveContains(query)
            || concept.canonicalTitle.localizedCaseInsensitiveContains(query)
            || concept.aliasesText.localizedCaseInsensitiveContains(query)
            || concept.oneLineExplanation.localizedCaseInsensitiveContains(query)
            || tags.contains { $0.localizedCaseInsensitiveContains(query) }
            || topics.contains { $0.localizedCaseInsensitiveContains(query) }
    }
}
