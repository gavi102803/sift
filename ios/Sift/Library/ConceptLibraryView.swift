import SwiftData
import SwiftUI

private enum LibraryScope: String, CaseIterable {
    case active = "Library"
    case recentlyDeleted = "Recently Deleted"
}

private enum LibrarySortOption: String, CaseIterable {
    case lastModified = "Last Modified"
    case recentlyViewed = "Recently Viewed"
    case dateCreated = "Date Created"
    case title = "Title"
}

struct ConceptLibraryView: View {
    @Environment(\.appServices) private var appServices
    @Environment(\.modelContext) private var modelContext
    @Query private var concepts: [Concept]
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
    @State private var scope: LibraryScope = .active
    @State private var sortOption: LibrarySortOption = .lastModified
    @State private var isSelecting = false
    @State private var isShowingNewCategoryForSelection = false
    @State private var isConfirmingArchive = false
    @State private var isApplyingBatchAction = false
    @State private var undoArchivedIds: [UUID] = []
    @State private var undoTask: Task<Void, Never>?

    private var visibleConcepts: [Concept] {
        concepts.filter { concept in
            switch scope {
            case .active:
                concept.captureStatus != CaptureStatus.archived.rawValue
            case .recentlyDeleted:
                concept.captureStatus == CaptureStatus.archived.rawValue
            }
        }
    }

    private var filteredConcepts: [Concept] {
        let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines)
        let filtered = visibleConcepts.filter { concept in
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
        return sorted(filtered)
    }

    private var allVisibleSelected: Bool {
        !filteredConcepts.isEmpty && filteredConcepts.allSatisfy { selectedConceptIds.contains($0.id) }
    }

    private var archiveSelectionPlan: ConceptArchiveSelectionPlan {
        ConceptArchiveSelectionPlan(
            concepts: concepts.filter { selectedConceptIds.contains($0.id) }
        )
    }

    private var trimmedSearchText: String {
        searchText.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private var emptyStateTitle: String {
        if !trimmedSearchText.isEmpty { return "No matching concepts" }
        return scope == .active ? "No concepts yet" : "Recently Deleted is empty"
    }

    private var emptyStateIcon: String {
        scope == .active ? "rectangle.stack.badge.plus" : "trash"
    }

    private var emptyStateDescription: String {
        scope == .active
            ? "Captured concepts will appear here."
            : "Cards you delete will remain available here to restore."
    }

    private var filterNames: [String] {
        ["All"] + userCategories.map(\.name)
    }

    private var userCategories: [Topic] {
        topics
            .filter { LibraryCategoryOwnership.isCategory($0) }
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
            assignment.topicId == selectedCategory.id && LibraryCategoryOwnership.isCategory(assignment)
        }
    }

    private var selectableConceptsForCurrentCategory: [Concept] {
        guard let selectedCategory else { return [] }
        let assignedIds = Set(
            conceptTopics
                .filter { $0.topicId == selectedCategory.id && LibraryCategoryOwnership.isCategory($0) }
                .map(\.conceptId)
        )
        return visibleConcepts.filter { !assignedIds.contains($0.id) }
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                titleRow
                searchField
                filterBar

                SiftEyebrow(
                    text: scope == .active ? "All Concepts" : "Recently Deleted",
                    trailing: "\(filteredConcepts.count)"
                )
                    .padding(.top, 4)

                if isRefreshing && concepts.isEmpty {
                    HStack {
                        Spacer()
                        ProgressView().tint(SiftColor.textMuted)
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
                        emptyStateTitle,
                        systemImage: trimmedSearchText.isEmpty ? emptyStateIcon : "magnifyingglass",
                        description: Text(
                            trimmedSearchText.isEmpty
                                ? emptyStateDescription
                                : "Try another title, alias, or explanation."
                        )
                    )
                    .frame(maxWidth: .infinity)
                    .siftCard(padding: 18)
                } else {
                    VStack(spacing: 10) {
                        ForEach(Array(filteredConcepts.enumerated()), id: \.element.id) { index, concept in
                            ConceptLibraryCard(
                                concept: concept,
                                tags: tagNames(for: concept),
                                topics: topicNames(for: concept),
                                organization: organizationText(for: concept),
                                emphasized: index == 0,
                                isSelecting: isSelecting,
                                isSelected: selectedConceptIds.contains(concept.id),
                                onToggleSelection: { toggleSelection(concept.id) }
                            )
                        }
                    }
                }
            }
            .padding(.horizontal, 20)
            .padding(.top, 8)
            .padding(.bottom, SiftLayout.tabBarClearance + (isSelecting ? 72 : 0))
        }
        .scrollContentBackground(.hidden)
        .siftScreenBackground()
        .navigationBarHidden(true)
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
        .alert("New Category", isPresented: $isShowingNewCategoryForSelection) {
            TextField("Category name", text: $draftCategoryName)
            Button("Cancel", role: .cancel) {}
            Button("Create") {
                createCategoryFromSelection()
            }
            .disabled(draftCategoryName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
        } message: {
            Text("The selected cards will be added to this category.")
        }
        .confirmationDialog(
            archiveSelectionPlan.confirmationTitle,
            isPresented: $isConfirmingArchive,
            titleVisibility: .visible
        ) {
            Button(archiveSelectionPlan.confirmationActionTitle, role: .destructive) {
                Task { await archiveSelection() }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text(archiveSelectionPlan.confirmationMessage)
        }
        .overlay(alignment: .bottom) {
            VStack(spacing: 10) {
                if !undoArchivedIds.isEmpty {
                    undoBanner
                        .transition(.move(edge: .bottom).combined(with: .opacity))
                }
                if isSelecting {
                    selectionToolbar
                        .transition(.move(edge: .bottom).combined(with: .opacity))
                }
            }
            .padding(.horizontal, 20)
            .padding(.bottom, SiftLayout.tabBarClearance - 8)
        }
        .animation(.snappy(duration: 0.25), value: isSelecting)
        .animation(.snappy(duration: 0.25), value: undoArchivedIds)
        .refreshable {
            await refreshConcepts()
        }
        .task {
            await refreshConcepts()
        }
        .onDisappear {
            undoTask?.cancel()
        }
    }

    private var titleRow: some View {
        HStack(alignment: .center) {
            Text(isSelecting ? "\(selectedConceptIds.count) Selected" : scope.rawValue)
                .font(SiftFont.screenTitle)
                .tracking(-0.8)
                .foregroundStyle(SiftColor.textPrimary)
                .lineLimit(1)
                .minimumScaleFactor(0.78)
            Spacer(minLength: 8)
            if isSelecting {
                Button(allVisibleSelected ? "Deselect All" : "Select All") {
                    toggleSelectAll()
                }
                .font(SiftFont.sans(13, .medium))
                .foregroundStyle(SiftColor.accent)
                Button("Done") {
                    exitSelectionMode()
                }
                .font(SiftFont.sans(14, .semibold))
                .foregroundStyle(SiftColor.textPrimary)
            } else {
                Menu {
                    Picker("Sort", selection: $sortOption) {
                        ForEach(LibrarySortOption.allCases, id: \.self) { option in
                            Label(option.rawValue, systemImage: sortIcon(for: option))
                                .tag(option)
                        }
                    }
                } label: {
                    Image(systemName: "arrow.up.arrow.down")
                        .font(.system(size: 15, weight: .medium))
                        .foregroundStyle(SiftColor.textSecondary)
                        .frame(width: 38, height: 38)
                        .background(SiftColor.surfaceSoft, in: RoundedRectangle(cornerRadius: 11, style: .continuous))
                        .overlay(
                            RoundedRectangle(cornerRadius: 11, style: .continuous)
                                .strokeBorder(SiftColor.hairline, lineWidth: 1)
                        )
                }
                .accessibilityLabel("Sort concepts")

                if !filteredConcepts.isEmpty {
                    Button("Select") {
                        isSelecting = true
                    }
                    .font(SiftFont.sans(14, .semibold))
                    .foregroundStyle(SiftColor.accent)
                }
            }
        }
    }

    private var searchField: some View {
        HStack(spacing: 10) {
            Image(systemName: "magnifyingglass")
                .font(.system(size: 16, weight: .regular))
                .foregroundStyle(SiftColor.textMuted)
            TextField(
                "",
                text: $searchText,
                prompt: Text("Search concepts & tags").foregroundColor(SiftColor.textFaint)
            )
            .textFieldStyle(.plain)
            .font(SiftFont.body)
            .foregroundStyle(SiftColor.textPrimary)
            .tint(SiftColor.accent)
            .textInputAutocapitalization(.never)
            if !searchText.isEmpty {
                Button {
                    searchText = ""
                } label: {
                    Image(systemName: "xmark.circle.fill")
                        .foregroundStyle(SiftColor.textFaint)
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Clear search")
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 12)
        .background(SiftColor.surfaceSoft, in: RoundedRectangle(cornerRadius: SiftRadius.field, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: SiftRadius.field, style: .continuous)
                .strokeBorder(SiftColor.hairline, lineWidth: 1)
        }
    }

    private var filterBar: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                if scope == .active {
                    ForEach(filterNames, id: \.self) { name in
                        Button {
                            selectedFilter = name
                        } label: {
                            Text(name)
                                .font(SiftFont.sans(13, .medium))
                                .padding(.horizontal, 13)
                                .padding(.vertical, 8)
                                .foregroundStyle(selectedFilter == name ? .white : SiftColor.textBody)
                                .background(
                                    selectedFilter == name ? SiftColor.accent : SiftColor.surfaceSoft,
                                    in: RoundedRectangle(cornerRadius: 9, style: .continuous)
                                )
                                .overlay {
                                    RoundedRectangle(cornerRadius: 9, style: .continuous)
                                        .strokeBorder(selectedFilter == name ? .clear : SiftColor.hairline, lineWidth: 1)
                                }
                        }
                        .buttonStyle(.plain)
                    }
                    Button {
                        prepareCategoryAction()
                    } label: {
                        Label(
                            selectedCategory == nil ? "New" : "Add",
                            systemImage: selectedCategory == nil ? "plus" : "rectangle.stack.badge.plus"
                        )
                        .font(SiftFont.sans(13, .medium))
                        .padding(.horizontal, 12)
                        .padding(.vertical, 8)
                        .foregroundStyle(SiftColor.accent)
                        .background(SiftColor.surfaceSoft, in: RoundedRectangle(cornerRadius: 9, style: .continuous))
                    }
                    .buttonStyle(.plain)
                }

                Button {
                    scope = scope == .active ? .recentlyDeleted : .active
                    selectedFilter = "All"
                    exitSelectionMode()
                } label: {
                    Label(
                        scope == .active ? "Recently Deleted" : "Back to Library",
                        systemImage: scope == .active ? "trash" : "chevron.backward"
                    )
                    .font(SiftFont.sans(13, .medium))
                    .padding(.horizontal, 12)
                    .padding(.vertical, 8)
                    .foregroundStyle(SiftColor.textMuted)
                    .background(SiftColor.surfaceSoft, in: RoundedRectangle(cornerRadius: 9, style: .continuous))
                }
                .buttonStyle(.plain)
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
            LibraryCategoryOwnership.isCategory(topic) && topic.name.caseInsensitiveCompare(name) == .orderedSame
        }) {
            return existing
        }
        let topic = Topic(name: name, source: LibraryCategoryOwnership.categorySource)
        modelContext.insert(topic)
        return topic
    }

    private func addConcepts(_ conceptIds: Set<UUID>, to category: Topic) {
        let existingConceptIds = Set(
            conceptTopics
                .filter { $0.topicId == category.id && LibraryCategoryOwnership.isCategory($0) }
                .map(\.conceptId)
        )
        for conceptId in conceptIds where !existingConceptIds.contains(conceptId) {
            modelContext.insert(
                ConceptTopic(
                    conceptId: conceptId,
                    topicId: category.id,
                    source: LibraryCategoryOwnership.categorySource
                )
            )
        }
    }

    private var selectionToolbar: some View {
        HStack(spacing: 12) {
            if scope == .active {
                Menu {
                    ForEach(userCategories) { category in
                        Button(category.name) {
                            addConcepts(selectedConceptIds, to: category)
                            exitSelectionMode()
                        }
                    }
                    Divider()
                    Button {
                        draftCategoryName = ""
                        isShowingNewCategoryForSelection = true
                    } label: {
                        Label("New Category", systemImage: "plus")
                    }
                } label: {
                    Label("Add to Category", systemImage: "folder.badge.plus")
                        .frame(maxWidth: .infinity)
                }
                .disabled(selectedConceptIds.isEmpty || isApplyingBatchAction)

                Divider().frame(height: 24)

                Button(role: .destructive) {
                    isConfirmingArchive = true
                } label: {
                    Label("Delete", systemImage: "trash")
                        .frame(maxWidth: .infinity)
                }
                .disabled(selectedConceptIds.isEmpty || isApplyingBatchAction)
            } else {
                Button {
                    Task { await restoreSelection() }
                } label: {
                    Label("Restore", systemImage: "arrow.uturn.backward")
                        .frame(maxWidth: .infinity)
                }
                .disabled(selectedConceptIds.isEmpty || isApplyingBatchAction)
            }
        }
        .font(SiftFont.sans(14, .semibold))
        .foregroundStyle(SiftColor.textPrimary)
        .padding(.horizontal, 18)
        .frame(height: 56)
        .background(.ultraThinMaterial, in: Capsule())
        .overlay(Capsule().strokeBorder(SiftColor.hairline, lineWidth: 1))
        .shadow(color: .black.opacity(0.12), radius: 18, y: 8)
    }

    private var undoBanner: some View {
        HStack(spacing: 12) {
            Text("Moved \(undoArchivedIds.count) card\(undoArchivedIds.count == 1 ? "" : "s") to Recently Deleted")
                .font(SiftFont.sans(13, .medium))
                .foregroundStyle(SiftColor.textPrimary)
                .lineLimit(2)
            Spacer(minLength: 8)
            Button("Undo") {
                Task { await undoArchive() }
            }
            .font(SiftFont.sans(14, .semibold))
            .foregroundStyle(SiftColor.accent)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 13)
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .strokeBorder(SiftColor.hairline, lineWidth: 1)
        )
        .shadow(color: .black.opacity(0.12), radius: 18, y: 8)
    }

    private func toggleSelection(_ id: UUID) {
        if selectedConceptIds.contains(id) {
            selectedConceptIds.remove(id)
        } else {
            selectedConceptIds.insert(id)
        }
    }

    private func toggleSelectAll() {
        if allVisibleSelected {
            selectedConceptIds.subtract(filteredConcepts.map(\.id))
        } else {
            selectedConceptIds.formUnion(filteredConcepts.map(\.id))
        }
    }

    private func exitSelectionMode() {
        isSelecting = false
        selectedConceptIds = []
    }

    private func createCategoryFromSelection() {
        let name = draftCategoryName.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty else { return }
        addConcepts(selectedConceptIds, to: findOrCreateCategory(named: name))
        exitSelectionMode()
    }

    @MainActor
    private func archiveSelection() async {
        let selected = concepts.filter { selectedConceptIds.contains($0.id) }
        let plan = ConceptArchiveSelectionPlan(concepts: selected)
        guard plan.totalCount > 0 else { return }
        isApplyingBatchAction = true
        let previousStatuses = Dictionary(uniqueKeysWithValues: selected.map { ($0.id, $0.captureStatus) })
        let previousUpdatedAt = Dictionary(uniqueKeysWithValues: selected.map { ($0.id, $0.updatedAt) })
        selected.forEach { ConceptLocalStore(modelContext: modelContext).archiveConcept($0) }
        exitSelectionMode()

        func rollback() {
            selected.forEach { concept in
                concept.captureStatus = previousStatuses[concept.id] ?? CaptureStatus.ready.rawValue
                concept.updatedAt = previousUpdatedAt[concept.id] ?? concept.updatedAt
            }
            try? modelContext.save()
        }

        do {
            let store = ConceptLocalStore(modelContext: modelContext)
            if !plan.remoteConceptIds.isEmpty {
                let updated = try await appServices.apiClient.archiveConcepts(
                    ids: plan.remoteConceptIds
                )
                try store.upsertConcepts(from: updated)
            }
            for concept in selected where plan.localDraftIds.contains(concept.id) {
                store.deleteConcept(concept)
            }
            try modelContext.save()
            if !plan.remoteConceptIds.isEmpty {
                showUndo(for: plan.remoteConceptIds)
            }
        } catch is CancellationError {
            rollback()
        } catch {
            rollback()
            errorMessage = error.localizedDescription
        }
        isApplyingBatchAction = false
    }

    @MainActor
    private func restoreSelection() async {
        let ids = Array(selectedConceptIds)
        guard !ids.isEmpty else { return }
        isApplyingBatchAction = true
        do {
            let updated = try await appServices.apiClient.restoreConcepts(ids: ids)
            try ConceptLocalStore(modelContext: modelContext).upsertConcepts(from: updated)
            exitSelectionMode()
        } catch {
            errorMessage = error.localizedDescription
        }
        isApplyingBatchAction = false
    }

    private func showUndo(for ids: [UUID]) {
        undoTask?.cancel()
        undoArchivedIds = ids
        undoTask = Task {
            try? await Task.sleep(for: .seconds(6))
            guard !Task.isCancelled else { return }
            await MainActor.run { undoArchivedIds = [] }
        }
    }

    @MainActor
    private func undoArchive() async {
        let ids = undoArchivedIds
        guard !ids.isEmpty else { return }
        undoTask?.cancel()
        undoArchivedIds = []
        do {
            let updated = try await appServices.apiClient.restoreConcepts(ids: ids)
            try ConceptLocalStore(modelContext: modelContext).upsertConcepts(from: updated)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func sorted(_ concepts: [Concept]) -> [Concept] {
        concepts.sorted { lhs, rhs in
            switch sortOption {
            case .lastModified:
                if lhs.updatedAt != rhs.updatedAt { return lhs.updatedAt > rhs.updatedAt }
            case .recentlyViewed:
                let lhsDate = lhs.lastViewedAt ?? .distantPast
                let rhsDate = rhs.lastViewedAt ?? .distantPast
                if lhsDate != rhsDate { return lhsDate > rhsDate }
            case .dateCreated:
                if lhs.createdAt != rhs.createdAt { return lhs.createdAt > rhs.createdAt }
            case .title:
                let comparison = lhs.displayTitle.localizedCaseInsensitiveCompare(rhs.displayTitle)
                if comparison != .orderedSame { return comparison == .orderedAscending }
            }
            return lhs.id.uuidString < rhs.id.uuidString
        }
    }

    private func sortIcon(for option: LibrarySortOption) -> String {
        switch option {
        case .lastModified: "clock.arrow.circlepath"
        case .recentlyViewed: "eye"
        case .dateCreated: "calendar"
        case .title: "textformat"
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
        // Card-metadata topics only — local Library categories are surfaced via
        // the filter bar, never as card chips, so a same-named category/topic
        // pair never duplicates or confuses the source.
        CardTopicProjection.cardTopicNames(
            conceptId: concept.id,
            assignments: conceptTopics,
            topics: topics
        )
    }
}

private struct ConceptLibraryCard: View {
    var concept: Concept
    var tags: [String]
    var topics: [String]
    var organization: String
    var emphasized: Bool = false
    var isSelecting = false
    var isSelected = false
    var onToggleSelection: () -> Void = {}

    private var chips: [String] {
        Array((topics + tags).prefix(3))
    }

    var body: some View {
        Group {
            if isSelecting {
                Button(action: onToggleSelection) {
                    cardContent
                }
                .accessibilityLabel("\(isSelected ? "Deselect" : "Select") \(concept.displayTitle)")
            } else {
                NavigationLink(value: concept.id) {
                    cardContent
                }
            }
        }
        .buttonStyle(.plain)
    }

    private var cardContent: some View {
        HStack(alignment: .top, spacing: 12) {
            if isSelecting {
                Image(systemName: isSelected ? "checkmark.circle.fill" : "circle")
                    .font(.system(size: 22, weight: .medium))
                    .foregroundStyle(isSelected ? SiftColor.accent : SiftColor.textFaint)
                    .padding(.top, 9)
                    .transition(.scale.combined(with: .opacity))
            }
                SiftIconTile(systemName: ConceptGlyph.symbol(for: concept), accent: emphasized, size: 40)

                VStack(alignment: .leading, spacing: 8) {
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Text(concept.displayTitle)
                            .font(SiftFont.cardTitle)
                            .foregroundStyle(SiftColor.textPrimary)
                            .lineLimit(1)
                        Spacer(minLength: 8)
                        Text(relativeTime(for: concept.updatedAt))
                            .font(SiftFont.mono(10))
                            .tracking(0.5)
                            .foregroundStyle(SiftColor.textFaintest)
                    }

                    Text(concept.oneLineExplanation.isEmpty
                         ? CaptureStatusBadge.subtitle(for: concept.captureStatus)
                         : concept.oneLineExplanation)
                        .font(SiftFont.cardDesc)
                        .foregroundStyle(SiftColor.textMuted)
                        .lineLimit(1)
                        .lineSpacing(2)

                    if let badge = CaptureStatusBadge.label(for: concept.captureStatus) {
                        HStack(spacing: 5) {
                            Circle()
                                .fill(CaptureStatusBadge.color(for: concept.captureStatus))
                                .frame(width: 6, height: 6)
                            Text(badge)
                                .font(SiftFont.tag)
                                .foregroundStyle(SiftColor.textFaint)
                        }
                        .padding(.top, 1)
                    }

                    if !chips.isEmpty {
                        HStack(spacing: 6) {
                            ForEach(chips, id: \.self) { chip in
                                SiftChip(text: chip)
                            }
                        }
                        .padding(.top, 2)
                    } else if !organization.isEmpty {
                        Text(organization)
                            .font(SiftFont.tag)
                            .foregroundStyle(SiftColor.textFaint)
                            .lineLimit(1)
                    }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .siftCard(padding: 14)
        .overlay {
            RoundedRectangle(cornerRadius: SiftRadius.card, style: .continuous)
                .strokeBorder(isSelected ? SiftColor.accent.opacity(0.75) : .clear, lineWidth: 1.5)
        }
        .contentShape(Rectangle())
    }

    private func relativeTime(for date: Date) -> String {
        let interval = max(0, -date.timeIntervalSinceNow)
        if interval < 60 { return "Just now" }
        let formatter = RelativeDateTimeFormatter()
        formatter.unitsStyle = .abbreviated
        return formatter.localizedString(for: date, relativeTo: .now)
    }
}

/// Quiet, user-facing capture-state labels for Library cards. Distinguishes
/// draft / generating / ready / failed without exposing model or provider names.
enum CaptureStatusBadge {
    /// Short badge label, or nil for ready/archived (a finished card needs none).
    static func label(for status: String) -> String? {
        switch CaptureStatus(rawValue: status) {
        case .generating, .pendingGeneration: "Generating"
        case .draft: "Draft"
        case .generationFailed: "Needs retry"
        case .needsDisambiguation: "Needs review"
        case .ready, .archived, .none: nil
        }
    }

    /// Subtitle fallback when a card has no one-line explanation yet.
    static func subtitle(for status: String) -> String {
        switch CaptureStatus(rawValue: status) {
        case .generating, .pendingGeneration: "Generating your card…"
        case .draft: "Saved draft."
        case .generationFailed: "Generation didn’t finish — open to retry."
        case .needsDisambiguation: "Review possible matches."
        default: ""
        }
    }

    static func color(for status: String) -> Color {
        switch CaptureStatus(rawValue: status) {
        case .generationFailed: SiftColor.danger
        case .generating, .pendingGeneration: SiftColor.accent
        default: SiftColor.textFaint
        }
    }
}

/// Deterministic SF Symbol per concept, so cards read like distinct entries.
private enum ConceptGlyph {
    private static let symbols = [
        "cylinder.split.1x2", "shippingbox", "arrow.triangle.swap",
        "circle.grid.cross", "point.3.connected.trianglepath.dotted",
        "square.stack.3d.up", "function", "waveform.path.ecg"
    ]

    static func symbol(for concept: Concept) -> String {
        var hash = 5381
        for byte in concept.id.uuidString.utf8 {
            hash = ((hash << 5) &+ hash) &+ Int(byte)
        }
        return symbols[abs(hash) % symbols.count]
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
