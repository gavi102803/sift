import SwiftData
import SwiftUI

struct ConceptLibraryView: View {
    @Environment(\.appServices) private var appServices
    @Environment(\.modelContext) private var modelContext
    @Query(sort: \Concept.updatedAt, order: .reverse) private var concepts: [Concept]
    @State private var searchText = ""
    @State private var isRefreshing = false
    @State private var errorMessage: String?

    private var filteredConcepts: [Concept] {
        let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !query.isEmpty else { return concepts }
        return concepts.filter { concept in
            concept.displayTitle.localizedCaseInsensitiveContains(query)
                || concept.canonicalTitle.localizedCaseInsensitiveContains(query)
                || concept.oneLineExplanation.localizedCaseInsensitiveContains(query)
        }
    }

    private var trimmedSearchText: String {
        searchText.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    var body: some View {
        List {
            if isRefreshing && concepts.isEmpty {
                HStack {
                    Spacer()
                    ProgressView()
                    Spacer()
                }
            }

            if let errorMessage {
                Text(errorMessage)
                    .font(.footnote)
                    .foregroundStyle(.red)
            }

            if filteredConcepts.isEmpty {
                ContentUnavailableView(
                    trimmedSearchText.isEmpty ? "No concepts yet" : "No matching concepts",
                    systemImage: trimmedSearchText.isEmpty ? "rectangle.stack.badge.plus" : "magnifyingglass",
                    description: Text(
                        trimmedSearchText.isEmpty
                            ? "Captured concepts will appear here."
                            : "Try another title, alias, or explanation."
                    )
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
        .refreshable {
            await refreshConcepts()
        }
        .task {
            await refreshConcepts()
        }
        .navigationDestination(for: UUID.self) { conceptId in
            ConceptDetailView(conceptId: conceptId)
        }
    }

    private func refreshConcepts() async {
        guard !isRefreshing else { return }
        isRefreshing = true
        defer {
            isRefreshing = false
        }
        errorMessage = nil
        do {
            let concepts = try await appServices.apiClient.listConcepts()
            try ConceptLocalStore(modelContext: modelContext).upsertConcepts(from: concepts)
        } catch is CancellationError {
            return
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

#Preview {
    NavigationStack {
        ConceptLibraryView()
    }
    .environment(\.appServices, .preview)
}
