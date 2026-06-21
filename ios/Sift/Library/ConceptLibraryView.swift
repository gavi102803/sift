import SwiftData
import SwiftUI

struct ConceptLibraryView: View {
    @Query(sort: \Concept.updatedAt, order: .reverse) private var concepts: [Concept]
    @State private var searchText = ""

    private var filteredConcepts: [Concept] {
        let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !query.isEmpty else { return concepts }
        return concepts.filter { concept in
            concept.displayTitle.localizedCaseInsensitiveContains(query)
                || concept.canonicalTitle.localizedCaseInsensitiveContains(query)
                || concept.oneLineExplanation.localizedCaseInsensitiveContains(query)
        }
    }

    var body: some View {
        List {
            if filteredConcepts.isEmpty {
                ContentUnavailableView(
                    "No matching concepts",
                    systemImage: "magnifyingglass",
                    description: Text("Try another title, alias, or explanation.")
                )
            } else {
                Section("All Concepts") {
                    ForEach(filteredConcepts) { concept in
                        NavigationLink(value: concept.id) {
                            VStack(alignment: .leading, spacing: 4) {
                                Text(concept.displayTitle)
                                    .font(.body.weight(.medium))
                                Text(concept.oneLineExplanation.isEmpty ? concept.captureStatus : concept.oneLineExplanation)
                                    .font(.footnote)
                                    .foregroundStyle(.secondary)
                                    .lineLimit(2)
                            }
                            .padding(.vertical, 4)
                        }
                    }
                }
            }
        }
        .navigationTitle("Library")
        .searchable(text: $searchText, prompt: "Search concepts")
        .navigationDestination(for: UUID.self) { conceptId in
            ConceptDetailView(conceptId: conceptId)
        }
    }
}

#Preview {
    NavigationStack {
        ConceptLibraryView()
    }
}

