import SwiftData
import SwiftUI

struct ConceptLibraryView: View {
    @Environment(\.appServices) private var appServices
    @Environment(\.modelContext) private var modelContext
    @Query(sort: \Concept.updatedAt, order: .reverse) private var concepts: [Concept]
    @Query(sort: \Tag.name) private var tags: [Tag]
    @Query private var conceptTags: [ConceptTag]
    @Query(sort: \Topic.name) private var topics: [Topic]
    @Query private var conceptTopics: [ConceptTopic]
    @Binding var searchText: String
    @State private var isRefreshing = false
    @State private var errorMessage: String?
    @State private var selectedFilter = "All"
    @State private var isShowingCreateCategory = false
    @State private var isShowingAddToCategory = false
    @State private var draftCategoryName = ""
    @State private var selectedConceptIds: Set<UUID> = []

    private var visibleConcepts: [Concept] {
        concepts.filter { $0.captureStatus != CaptureStatus.archived.rawValue }
    }

    private var filteredConcepts: [Concept] {
        let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines)
        return visibleConcepts.filter { concept in
            let conceptTags = tagNames(for: concept)
            let conceptTopicNames = topicNames(for: concept)
            let matchesFilter = selectedCategory == nil || conceptIsInSelectedCategory(concept)
            guard matchesFilter else { return false }
            guard !query.isEmpty else { return true }
            return ConceptSearchIndex.matches(
                query: query,
                concept: concept,
                tags: conceptTags,
                topics: conceptTopicNames
            )
        }
    }

    private var trimmedSearchText: String {
        searchText.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private var filterNames: [String] {
        ["All"] + userCategories.map(\.name)
    }

    private var userCategories: [Topic] {
        topics
            .filter { $0.source == "category" }
            .sorted { lhs, rhs in
                lhs.name.localizedCaseInsensitiveCompare(rhs.name) == .orderedAscending
            }
    }

    private var selectedCategory: Topic? {
        userCategories.first { $0.name == selectedFilter }
    }

    private var selectedCategoryAssignments: [ConceptTopic] {
        guard let selectedCategory else { return [] }
        return conceptTopics.filter { assignment in
            assignment.topicId == selectedCategory.id && assignment.source == "category"
        }
    }

    private var selectableConceptsForCurrentCategory: [Concept] {
        guard let selectedCategory else { return [] }
        let assignedIds = Set(
            conceptTopics
                .filter { $0.topicId == selectedCategory.id && $0.source == "category" }
                .map(\.conceptId)
        )
        return visibleConcepts.filter { !assignedIds.contains($0.id) }
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                searchField
                filterBar

                HStack {
                    Text("All Concepts")
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(.secondary)
                    Spacer()
                    Text("\(filteredConcepts.count) items")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                if isRefreshing && concepts.isEmpty {
                    HStack {
                        Spacer()
                        ProgressView()
                        Spacer()
                    }
                }

                if let errorMessage {
                    InlineErrorView(message: errorMessage) {
                        Task {
                            await refreshConcepts()
                        }
                    }
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
                    .frame(maxWidth: .infinity)
                    .siftCard(padding: 18)
                } else {
                    ForEach(filteredConcepts) { concept in
                        ConceptLibraryCard(
                            concept: concept,
                            tags: tagNames(for: concept),
                            topics: topicNames(for: concept),
                            organization: organizationText(for: concept)
                        )
                    }
                }
            }
            .padding(20)
            .padding(.bottom, 20)
        }
        .scrollContentBackground(.hidden)
        .siftScreenBackground()
        .navigationTitle("Library")
        .toolbar {
            Button {
                prepareCategoryAction()
            } label: {
                Image(systemName: selectedCategory == nil ? "plus" : "rectangle.stack.badge.plus")
            }
            .accessibilityLabel(selectedCategory == nil ? "Create category" : "Add concepts to category")
        }
        .sheet(isPresented: $isShowingCreateCategory) {
            NavigationStack {
                CategoryEditorSheet(
                    title: "New Category",
                    categoryName: $draftCategoryName,
                    concepts: visibleConcepts,
                    selectedConceptIds: $selectedConceptIds,
                    saveTitle: "Create",
                    onCancel: {
                        isShowingCreateCategory = false
                    },
                    onSave: {
                        createCategory()
                    }
                )
            }
        }
        .sheet(isPresented: $isShowingAddToCategory) {
            NavigationStack {
                CategoryEditorSheet(
                    title: selectedFilter,
                    categoryName: .constant(selectedFilter),
                    concepts: selectableConceptsForCurrentCategory,
                    selectedConceptIds: $selectedConceptIds,
                    saveTitle: "Add",
                    showsNameField: false,
                    emptyText: "All concepts are already in this category.",
                    onCancel: {
                        isShowingAddToCategory = false
                    },
                    onSave: {
                        addSelectedConceptsToCategory()
                    }
                )
            }
        }
        .refreshable {
            await refreshConcepts()
        }
        .task {
            await refreshConcepts()
        }
    }

    private var searchField: some View {
        HStack(spacing: 10) {
            Image(systemName: "magnifyingglass")
                .foregroundStyle(.secondary)
            TextField("Search concepts...", text: $searchText)
                .textFieldStyle(.plain)
                .textInputAutocapitalization(.never)
            if !searchText.isEmpty {
                Button {
                    searchText = ""
                } label: {
                    Image(systemName: "xmark.circle.fill")
                        .foregroundStyle(.tertiary)
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Clear search")
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 12)
        .background(SiftTheme.elevatedSurface, in: Capsule())
        .overlay {
            Capsule().stroke(SiftTheme.border, lineWidth: 1)
        }
    }

    private var filterBar: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(filterNames, id: \.self) { name in
                    Button {
                        selectedFilter = name
                    } label: {
                        Text(name)
                            .font(.caption.weight(.medium))
                            .padding(.horizontal, 12)
                            .padding(.vertical, 8)
                            .foregroundStyle(selectedFilter == name ? .white : .primary)
                            .background(
                                selectedFilter == name ? Color.accentColor : SiftTheme.elevatedSurface,
                                in: Capsule()
                            )
                            .overlay {
                                Capsule().stroke(SiftTheme.border, lineWidth: 1)
                            }
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.vertical, 2)
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
            let store = ConceptLocalStore(modelContext: modelContext)
            try store.upsertConcepts(from: concepts)
            try store.pruneLocalMirrorsMissingFromRemote(keeping: Set(concepts.map(\.id)))
        } catch is CancellationError {
            return
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func prepareCategoryAction() {
        selectedConceptIds = []
        if selectedCategory == nil {
            draftCategoryName = ""
            isShowingCreateCategory = true
        } else {
            isShowingAddToCategory = true
        }
    }

    private func createCategory() {
        let name = draftCategoryName.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty else { return }
        let category = findOrCreateCategory(named: name)
        addConcepts(selectedConceptIds, to: category)
        selectedFilter = category.name
        isShowingCreateCategory = false
    }

    private func addSelectedConceptsToCategory() {
        guard let selectedCategory else { return }
        addConcepts(selectedConceptIds, to: selectedCategory)
        isShowingAddToCategory = false
    }

    private func findOrCreateCategory(named name: String) -> Topic {
        if let existing = topics.first(where: { topic in
            topic.source == "category" && topic.name.caseInsensitiveCompare(name) == .orderedSame
        }) {
            return existing
        }
        let topic = Topic(name: name, source: "category")
        modelContext.insert(topic)
        return topic
    }

    private func addConcepts(_ conceptIds: Set<UUID>, to category: Topic) {
        let existingConceptIds = Set(
            conceptTopics
                .filter { $0.topicId == category.id && $0.source == "category" }
                .map(\.conceptId)
        )
        for conceptId in conceptIds where !existingConceptIds.contains(conceptId) {
            modelContext.insert(
                ConceptTopic(
                    conceptId: conceptId,
                    topicId: category.id,
                    source: "category"
                )
            )
        }
    }

    private func conceptIsInSelectedCategory(_ concept: Concept) -> Bool {
        selectedCategoryAssignments.contains { assignment in
            assignment.conceptId == concept.id
        }
    }

    private func organizationText(for concept: Concept) -> String {
        let topicText = topicNames(for: concept).joined(separator: ", ")
        let tagText = tagNames(for: concept).joined(separator: ", ")
        if topicText.isEmpty {
            return tagText
        }
        if tagText.isEmpty {
            return topicText
        }
        return "\(topicText) · \(tagText)"
    }

    private func tagNames(for concept: Concept) -> [String] {
        let assignedIds = Set(
            conceptTags
                .filter { $0.conceptId == concept.id }
                .map(\.tagId)
        )
        return tags
            .filter { assignedIds.contains($0.id) }
            .map(\.name)
    }

    private func topicNames(for concept: Concept) -> [String] {
        let assignedIds = Set(
            conceptTopics
                .filter { $0.conceptId == concept.id }
                .map(\.topicId)
        )
        return topics
            .filter { assignedIds.contains($0.id) }
            .map(\.name)
    }
}

private struct ConceptLibraryCard: View {
    var concept: Concept
    var tags: [String]
    var topics: [String]
    var organization: String

    private var chips: [String] {
        Array((topics + tags).prefix(3))
    }

    var body: some View {
        NavigationLink(value: concept.id) {
            HStack(alignment: .top, spacing: 12) {
                Image(systemName: "link")
                    .font(.headline)
                    .foregroundStyle(Color.accentColor)
                    .frame(width: 38, height: 38)
                    .background(SiftTheme.accentSoft, in: RoundedRectangle(cornerRadius: 10))

                VStack(alignment: .leading, spacing: 8) {
                    HStack(alignment: .top, spacing: 8) {
                        VStack(alignment: .leading, spacing: 4) {
                            Text(concept.displayTitle)
                                .font(.body.weight(.semibold))
                                .foregroundStyle(.primary)
                                .lineLimit(1)
                            Text(concept.oneLineExplanation.isEmpty ? concept.captureStatus : concept.oneLineExplanation)
                                .font(.footnote)
                                .foregroundStyle(.secondary)
                                .lineLimit(2)
                        }
                        Spacer(minLength: 8)
                        Text(relativeTime(for: concept.updatedAt))
                            .font(.caption2)
                            .foregroundStyle(.tertiary)
                    }

                    if !chips.isEmpty {
                        HStack(spacing: 6) {
                            ForEach(chips, id: \.self) { chip in
                                Text(chip)
                                    .font(.caption2.weight(.medium))
                                    .foregroundStyle(.secondary)
                                    .lineLimit(1)
                                    .truncationMode(.tail)
                                    .frame(maxWidth: 86)
                                    .padding(.horizontal, 8)
                                    .padding(.vertical, 4)
                                    .background(SiftTheme.subtleFill, in: Capsule())
                            }
                        }
                    } else if !organization.isEmpty {
                        Text(organization)
                            .font(.caption)
                            .foregroundStyle(.tertiary)
                            .lineLimit(1)
                    }
                }

                Image(systemName: "ellipsis")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                    .padding(.top, 2)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .siftCard(padding: 12)
        }
        .buttonStyle(.plain)
    }

    private func relativeTime(for date: Date) -> String {
        if abs(date.timeIntervalSinceNow) < 60 {
            return "now"
        }
        let formatter = RelativeDateTimeFormatter()
        formatter.unitsStyle = .abbreviated
        return formatter.localizedString(for: date, relativeTo: .now)
    }
}

private struct CategoryEditorSheet: View {
    var title: String
    @Binding var categoryName: String
    var concepts: [Concept]
    @Binding var selectedConceptIds: Set<UUID>
    var saveTitle: String
    var showsNameField = true
    var emptyText = "No concepts available."
    var onCancel: () -> Void
    var onSave: () -> Void

    private var canSave: Bool {
        if showsNameField {
            return !categoryName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        }
        return !selectedConceptIds.isEmpty
    }

    var body: some View {
        List {
            if showsNameField {
                Section("Category") {
                    TextField("Category name", text: $categoryName)
                        .textInputAutocapitalization(.words)
                }
            }

            Section("Knowledge Cards") {
                if concepts.isEmpty {
                    Text(emptyText)
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                } else {
                    ForEach(concepts) { concept in
                        Button {
                            toggle(concept.id)
                        } label: {
                            HStack(spacing: 12) {
                                Image(systemName: selectedConceptIds.contains(concept.id) ? "checkmark.circle.fill" : "circle")
                                    .foregroundStyle(selectedConceptIds.contains(concept.id) ? Color.accentColor : Color.secondary)
                                VStack(alignment: .leading, spacing: 4) {
                                    Text(concept.displayTitle)
                                        .font(.body.weight(.medium))
                                        .foregroundStyle(.primary)
                                    Text(concept.oneLineExplanation.isEmpty ? concept.captureStatus : concept.oneLineExplanation)
                                        .font(.footnote)
                                        .foregroundStyle(.secondary)
                                        .lineLimit(2)
                                }
                            }
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
        }
        .navigationTitle(title)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .cancellationAction) {
                Button("Cancel", action: onCancel)
            }
            ToolbarItem(placement: .confirmationAction) {
                Button(saveTitle, action: onSave)
                    .disabled(!canSave)
            }
        }
    }

    private func toggle(_ conceptId: UUID) {
        if selectedConceptIds.contains(conceptId) {
            selectedConceptIds.remove(conceptId)
        } else {
            selectedConceptIds.insert(conceptId)
        }
    }
}

#Preview {
    NavigationStack {
        ConceptLibraryView(searchText: .constant(""))
    }
    .environment(\.appServices, .preview)
}
