import SwiftData
import SwiftUI

enum ConceptDetailMode: Hashable {
    case overview
    case followUp
}

struct ConceptDetailView: View {
    @Environment(\.appServices) private var appServices
    @Environment(\.modelContext) private var modelContext
    @Query private var concepts: [Concept]
    @Query(sort: \Concept.displayTitle) private var allConcepts: [Concept]
    @Query private var proposals: [ConceptUpdateProposal]
    @Query private var relations: [ConceptRelation]
    @State private var followUpText = ""
    @State private var lastAnswerSource: AnswerSourceDTO?
    @State private var turns: [ConceptHistoryTurnDTO] = []
    @State private var conceptTagNames: [String] = []
    @State private var conceptTopicNames: [String] = []
    @State private var errorMessage: String?
    @State private var isSubmittingFollowUp = false
    @State private var isRefreshingConcept = false
    @State private var resolvingProposalId: UUID?
    @State private var resolvingRelationId: UUID?
    @State private var addingRelationTargetId: UUID?
    @State private var isEditingSummary = false
    @State private var editingBlockId: UUID?
    @State private var draftTitle = ""
    @State private var draftExplanation = ""
    @State private var draftTags = ""
    @State private var draftTopics = ""
    @State private var draftBlockContent = ""
    @State private var detailMode: ConceptDetailMode = .overview
    @Namespace private var detailTransition

    private var conceptId: UUID

    init(conceptId: UUID, initialMode: ConceptDetailMode = .overview) {
        self.conceptId = conceptId
        _detailMode = State(initialValue: initialMode)
        _concepts = Query(filter: #Predicate<Concept> { concept in
            concept.id == conceptId
        })
        _proposals = Query(
            filter: #Predicate<ConceptUpdateProposal> { proposal in
                proposal.conceptId == conceptId
            },
            sort: \ConceptUpdateProposal.createdAt,
            order: .reverse
        )
    }

    private var concept: Concept? {
        concepts.first
    }

    private var lastTurnSignature: String {
        guard let last = turns.last else { return "empty" }
        return "\(last.id.uuidString)-\(last.content.count)"
    }

    private var activeProposal: ConceptUpdateProposal? {
        proposals.first { proposal in
            proposal.status == ProposalStatus.proposed.rawValue
        }
    }

    var body: some View {
        Group {
            if let concept {
                ScrollViewReader { proxy in
                    ScrollView {
                        VStack(alignment: .leading, spacing: 20) {
                            if detailMode == .followUp {
                                Color.clear.frame(height: 92)
                            }
                            if detailMode == .overview {
                                header(for: concept)
                                    .matchedGeometryEffect(id: "knowledge-card", in: detailTransition)
                                    .transition(.move(edge: .bottom).combined(with: .opacity))
                            }
                            if isRefreshingConcept {
                                ProgressView()
                            }
                            if let errorMessage {
                                Text(errorMessage)
                                    .font(.footnote)
                                    .foregroundStyle(.red)
                            }
                            if let activeProposal {
                                proposalSection(
                                    activeProposal,
                                    concept: concept,
                                    operations: patchOperations(for: activeProposal)
                                )
                            }
                            if detailMode == .overview {
                                overviewSections(for: concept)
                            } else {
                                conversationSection(for: concept)
                            }
                            Color.clear
                                .frame(height: 1)
                                .id("conversation-bottom")
                        }
                        .padding(.horizontal, 18)
                        .padding(.top, 12)
                        .padding(.bottom, SiftLayout.tabBarClearance + 76)
                    }
                    .scrollContentBackground(.hidden)
                    .onChange(of: detailMode) { _, newValue in
                        guard newValue == .followUp else { return }
                        scrollToConversationBottom(proxy)
                    }
                    .onChange(of: turns.count) { _, _ in
                        scrollToConversationBottom(proxy)
                    }
                    .onChange(of: lastTurnSignature) { _, _ in
                        scrollToConversationBottom(proxy)
                    }
                }
                .safeAreaInset(edge: .top) {
                    if detailMode == .followUp {
                        compactKnowledgeCard(for: concept)
                            .matchedGeometryEffect(id: "knowledge-card", in: detailTransition)
                            .padding(.horizontal, 20)
                            .padding(.top, 6)
                            .padding(.bottom, 8)
                            .background(.ultraThinMaterial)
                            .transition(.move(edge: .top).combined(with: .opacity))
                    }
                }
                .safeAreaInset(edge: .bottom) {
                    followUpComposer
                }
            } else {
                if isRefreshingConcept {
                    ProgressView()
                } else {
                    ContentUnavailableView(
                        "Concept not found",
                        systemImage: "exclamationmark.magnifyingglass",
                        description: Text("This card may have been deleted.")
                    )
                }
            }
        }
        .siftScreenBackground()
        .navigationTitle(concept?.displayTitle ?? "Concept")
        .navigationBarTitleDisplayMode(.inline)
        .animation(.spring(response: 0.42, dampingFraction: 0.86), value: detailMode)
        .toolbar {
            if concept != nil {
                Button {
                    beginSummaryEdit()
                } label: {
                    Image(systemName: "square.and.pencil")
                }
                .accessibilityLabel("Edit concept")
            }
        }
        .sheet(isPresented: $isEditingSummary) {
            NavigationStack {
                ConceptSummaryEditor(
                    title: $draftTitle,
                    explanation: $draftExplanation,
                    tags: $draftTags,
                    topics: $draftTopics,
                    onCancel: {
                        isEditingSummary = false
                    },
                    onSave: {
                        Task {
                            await saveSummaryEdit()
                        }
                    }
                )
            }
        }
        .sheet(
            isPresented: Binding(
                get: { editingBlockId != nil },
                set: { if !$0 { editingBlockId = nil } }
            )
        ) {
            NavigationStack {
                NoteBlockEditor(
                    content: $draftBlockContent,
                    onCancel: {
                        editingBlockId = nil
                    },
                    onSave: {
                        Task {
                            await saveBlockEdit()
                        }
                    }
                )
            }
        }
        .task(id: conceptId) {
            await refreshConcept(conceptId)
            refreshOrganization(for: conceptId)
            await refreshTurns(conceptId)
            restoreFailedFollowUpDraft()
        }
    }

    private func scrollToConversationBottom(_ proxy: ScrollViewProxy) {
        guard detailMode == .followUp else { return }
        Task { @MainActor in
            try? await Task.sleep(for: .milliseconds(60))
            withAnimation(.easeOut(duration: 0.22)) {
                proxy.scrollTo("conversation-bottom", anchor: .bottom)
            }
        }
    }

    @ViewBuilder
    private func overviewSections(for concept: Concept) -> some View {
        organizationSection
        relatedConceptsSection(for: concept)
        noteSection(for: concept)
    }

    private func header(for concept: Concept) -> some View {
        VStack(alignment: .leading, spacing: 18) {
            VStack(alignment: .leading, spacing: 14) {
                SiftIconTile(
                    systemName: "sparkles",
                    accent: true,
                    size: 48,
                    radius: 13
                )
                Text(concept.displayTitle)
                    .font(SiftFont.pageTitle)
                    .tracking(-0.6)
                    .foregroundStyle(SiftColor.textPrimary)
                    .lineLimit(3)
            }

            VStack(spacing: 12) {
                PropertyRow(icon: "chart.line.uptrend.xyaxis", label: "Maturity") {
                    if concept.maturity.lowercased() == "initial" {
                        SiftChip(text: concept.maturity.capitalized)
                    } else {
                        AccentWashChip(text: concept.maturity.capitalized)
                    }
                }
                PropertyRow(icon: "checkmark.seal", label: "Status") {
                    SiftChip(text: statusLabel(concept.captureStatus))
                }
                if !conceptTopicNames.isEmpty {
                    PropertyRow(icon: "folder", label: "Topics") {
                        chipWrap(conceptTopicNames)
                    }
                }
                if !conceptTagNames.isEmpty {
                    PropertyRow(icon: "tag", label: "Tags") {
                        chipWrap(conceptTagNames)
                    }
                }
            }

            if !concept.oneLineExplanation.isEmpty {
                HStack(alignment: .top, spacing: 12) {
                    Image(systemName: "lightbulb")
                        .font(.system(size: 16, weight: .regular))
                        .foregroundStyle(SiftColor.accent)
                        .padding(.top, 1)
                    Text(concept.oneLineExplanation)
                        .font(SiftFont.body)
                        .foregroundStyle(SiftColor.textSecondary)
                        .lineSpacing(4)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(14)
                .background(SiftColor.surfaceSoft, in: RoundedRectangle(cornerRadius: SiftRadius.card, style: .continuous))
                .overlay {
                    RoundedRectangle(cornerRadius: SiftRadius.card, style: .continuous)
                        .strokeBorder(SiftColor.hairline, lineWidth: 1)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    @ViewBuilder
    private func chipWrap(_ values: [String]) -> some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: 6) {
                ForEach(values, id: \.self) { SiftChip(text: $0) }
            }
            HStack(spacing: 6) {
                ForEach(values.prefix(2), id: \.self) { SiftChip(text: $0) }
            }
        }
    }

    private func statusLabel(_ status: String) -> String {
        switch CaptureStatus(rawValue: status) {
        case .ready: "Ready"
        case .generating, .pendingGeneration, .draft: "Generating"
        case .generationFailed: "Failed"
        case .needsDisambiguation: "Review"
        case .archived: "Archived"
        case .none: status
        }
    }

    private func compactKnowledgeCard(for concept: Concept) -> some View {
        Button {
            withAnimation(.spring(response: 0.42, dampingFraction: 0.86)) {
                detailMode = .overview
            }
        } label: {
            HStack(spacing: 12) {
                Image(systemName: "link")
                    .font(.headline)
                    .foregroundStyle(Color.accentColor)
                    .frame(width: 42, height: 42)
                    .background(SiftTheme.accentSoft, in: RoundedRectangle(cornerRadius: 12))

                VStack(alignment: .leading, spacing: 4) {
                    Text(concept.displayTitle)
                        .font(.headline)
                        .foregroundStyle(.primary)
                        .lineLimit(1)
                    Text(concept.oneLineExplanation.isEmpty ? concept.captureStatus : concept.oneLineExplanation)
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                }

                Spacer(minLength: 8)
                Image(systemName: "chevron.down")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .siftCard(padding: 12)
        }
        .buttonStyle(.plain)
        .accessibilityLabel("Show concept overview")
    }

    private var organizationSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Organization")
                .font(.headline)

            EditableChipsRow(
                title: "Topics",
                values: conceptTopicNames,
                emptyText: "No topics",
                icon: "folder"
            )
            EditableChipsRow(
                title: "Tags",
                values: conceptTagNames,
                emptyText: "No tags",
                icon: "tag"
            )
        }
        .sectionCard()
    }

    private func relatedConceptsSection(for concept: Concept) -> some View {
        let relationRows = relatedRelationRows(for: concept)
        let candidates = relatedCandidates(for: concept)

        return VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("Related Concepts")
                    .font(.headline)
                Spacer()
                Menu {
                    if candidates.isEmpty {
                        Text("No concepts available")
                    } else {
                        ForEach(candidates) { candidate in
                            Button(candidate.displayTitle) {
                                Task {
                                    await addRelation(from: concept, to: candidate)
                                }
                            }
                        }
                    }
                } label: {
                    Image(systemName: "plus")
                        .frame(width: 28, height: 28)
                }
                .accessibilityLabel("Add related concept")
                .disabled(addingRelationTargetId != nil)
            }

            if relationRows.isEmpty {
                Text("No related concepts yet")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
            } else {
                ForEach(relationRows) { row in
                    RelatedConceptRow(row: row) {
                        Task {
                            await removeRelation(row.relation)
                        }
                    }
                    .disabled(resolvingRelationId != nil)
                }
            }
        }
        .sectionCard()
    }

    private func noteSection(for concept: Concept) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Note")
                .font(.headline)

            if let blocks = concept.note?.blocks, !blocks.isEmpty {
                ForEach(blocks) { block in
                    NoteBlockView(block: block) {
                        beginBlockEdit(block)
                    }
                }
            } else {
                ContentUnavailableView(
                    emptyNoteTitle(for: concept),
                    systemImage: emptyNoteIcon(for: concept),
                    description: Text(emptyNoteDescription(for: concept))
                )
            }
        }
        .sectionCard()
    }

    private func emptyNoteTitle(for concept: Concept) -> String {
        switch CaptureStatus(rawValue: concept.captureStatus) {
        case .draft, .pendingGeneration, .generating:
            return "Generating concept"
        case .generationFailed:
            return "Generation failed"
        default:
            return "No note yet"
        }
    }

    private func emptyNoteIcon(for concept: Concept) -> String {
        switch CaptureStatus(rawValue: concept.captureStatus) {
        case .generationFailed:
            return "exclamationmark.triangle"
        case .draft, .pendingGeneration, .generating:
            return "hourglass"
        default:
            return "doc.text"
        }
    }

    private func emptyNoteDescription(for concept: Concept) -> String {
        switch CaptureStatus(rawValue: concept.captureStatus) {
        case .draft, .pendingGeneration, .generating:
            return "Sift is preparing the first card. You can stay here while it works."
        case .generationFailed:
            return "Return to Record to retry or archive this saved capture."
        default:
            return "Generate or edit this concept to start the card."
        }
    }

    private func conversationSection(for concept: Concept) -> some View {
        VStack(alignment: .leading, spacing: 18) {
            if turns.isEmpty {
                if detailMode == .followUp && ConceptStatusRules.canSubmitFollowUp(concept.captureStatus) {
                    InitialConceptExchange(concept: concept)
                } else {
                    ContentUnavailableView(
                        emptyConversationTitle(for: concept),
                        systemImage: emptyConversationIcon(for: concept),
                        description: Text(emptyConversationDescription(for: concept))
                    )
                }
            } else {
                ForEach(turns) { turn in
                    TurnRow(
                        turn: turn,
                        isStreaming: isStreamingTurn(turn),
                        showSavedChip: showsSavedChip(for: turn)
                    )
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func isStreamingTurn(_ turn: ConceptHistoryTurnDTO) -> Bool {
        isSubmittingFollowUp && turn.role == "assistant" && turn.id == turns.last?.id
    }

    private func showsSavedChip(for turn: ConceptHistoryTurnDTO) -> Bool {
        !isSubmittingFollowUp
            && turn.role == "assistant"
            && turn.id == turns.last?.id
            && lastAnswerSource != nil
            && !turn.content.isEmpty
    }

    private func emptyConversationTitle(for concept: Concept) -> String {
        switch CaptureStatus(rawValue: concept.captureStatus) {
        case .draft, .pendingGeneration, .generating:
            return "Building the first answer"
        default:
            return "No follow-ups yet"
        }
    }

    private func emptyConversationIcon(for concept: Concept) -> String {
        switch CaptureStatus(rawValue: concept.captureStatus) {
        case .draft, .pendingGeneration, .generating:
            return "sparkles"
        default:
            return "bubble.left.and.bubble.right"
        }
    }

    private func emptyConversationDescription(for concept: Concept) -> String {
        switch CaptureStatus(rawValue: concept.captureStatus) {
        case .draft, .pendingGeneration, .generating:
            return "Sift is turning your query into a concept card. You can stay here while it works."
        default:
            return "Ask a question to build this card over time."
        }
    }

    private func proposalSection(
        _ proposal: ConceptUpdateProposal,
        concept: Concept,
        operations: [PatchOperationDTO]
    ) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Label("Pending Update", systemImage: "checklist")
                    .font(.headline)
                Spacer()
            }

            Text(proposal.rationale)
                .font(.body)
                .foregroundStyle(.primary)

            if !operations.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    Text("Preview")
                        .font(.subheadline.weight(.semibold))
                    ForEach(operations) { operation in
                        ProposalPatchPreview(operation: operation, concept: concept)
                    }
                }
            }

            HStack(spacing: 10) {
                Button {
                    Task {
                        await mergeProposal(proposal)
                    }
                } label: {
                    if resolvingProposalId == proposal.id {
                        ProgressView()
                            .frame(maxWidth: .infinity)
                    } else {
                        Label("Confirm", systemImage: "checkmark")
                            .frame(maxWidth: .infinity)
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(resolvingProposalId != nil)

                Button {
                    Task {
                        await dismissProposal(proposal)
                    }
                } label: {
                    Label("Skip", systemImage: "xmark")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered)
                .disabled(resolvingProposalId != nil)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .background(SiftTheme.elevatedSurface, in: RoundedRectangle(cornerRadius: SiftTheme.cornerRadius))
        .overlay {
            RoundedRectangle(cornerRadius: SiftTheme.cornerRadius)
                .stroke(.orange.opacity(0.45), lineWidth: 1)
        }
    }

    private var canSubmitFollowUp: Bool {
        ConceptStatusRules.canSubmitFollowUp(concept?.captureStatus ?? "")
            && !followUpText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private var followUpComposer: some View {
        HStack(spacing: 12) {
            Image(systemName: "plus.circle")
                .font(.system(size: 22, weight: .regular))
                .foregroundStyle(SiftColor.textMuted)

            TextField(
                "",
                text: $followUpText,
                prompt: Text("Reply to Sift…").foregroundColor(Color(hex: 0x5E6166)),
                axis: .vertical
            )
            .textFieldStyle(.plain)
            .font(SiftFont.body)
            .foregroundStyle(SiftColor.textPrimary)
            .tint(SiftColor.accent)
            .lineLimit(1...4)

            Button {
                if let concept {
                    withAnimation(.spring(response: 0.42, dampingFraction: 0.86)) {
                        detailMode = .followUp
                    }
                    Task {
                        await submitFollowUp(for: concept)
                    }
                }
            } label: {
                Group {
                    if isSubmittingFollowUp {
                        ProgressView().tint(.white)
                    } else {
                        Image(systemName: "arrow.up")
                            .font(.system(size: 18, weight: .semibold))
                            .foregroundStyle(.white)
                    }
                }
                .frame(width: 40, height: 40)
                .background(
                    SiftColor.accent.opacity(canSubmitFollowUp ? 1 : 0.4),
                    in: RoundedRectangle(cornerRadius: SiftRadius.send, style: .continuous)
                )
            }
            .buttonStyle(.plain)
            .disabled(isSubmittingFollowUp || !canSubmitFollowUp)
            .accessibilityLabel("Submit follow-up")
        }
        .padding(.leading, 16)
        .padding(.trailing, 8)
        .padding(.vertical, 8)
        .background(SiftColor.surfaceSoft, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .strokeBorder(Color.white.opacity(0.09), lineWidth: 1)
        }
        .padding(.horizontal, 18)
        .padding(.bottom, SiftLayout.tabBarClearance)
    }

    private func submitFollowUp(for concept: Concept) async {
        let question = followUpText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !question.isEmpty else { return }

        isSubmittingFollowUp = true
        errorMessage = nil
        followUpText = ""
        withAnimation(.spring(response: 0.42, dampingFraction: 0.86)) {
            detailMode = .followUp
        }
        let userTurnId = UUID()
        let assistantTurnId = UUID()
        turns.append(ConceptHistoryTurnDTO(id: userTurnId, role: "user", content: question))
        turns.append(ConceptHistoryTurnDTO(id: assistantTurnId, role: "assistant", content: ""))
        do {
            var finalResponse: ConceptTurnResponse?
            for try await event in appServices.apiClient.streamTurn(
                conceptId: concept.id,
                request: ConceptTurnRequest(question: question)
            ) {
                if let delta = event.delta, !delta.isEmpty {
                    appendAssistantDelta(delta, turnId: assistantTurnId)
                }
                if let response = event.response {
                    finalResponse = response
                }
            }
            guard let response = finalResponse else {
                throw SiftStreamingError.incomplete
            }
            let store = ConceptLocalStore(modelContext: modelContext)
            _ = try store.upsertConcept(from: response.concept)
            refreshOrganization(for: response.concept.id)
            if let proposal = response.proposal {
                _ = try store.upsertProposal(proposal, conceptId: response.concept.id)
            }
            store.clearFailedFollowUpDrafts(for: concept, matching: question)
            lastAnswerSource = response.answerSource
            replaceAssistantAnswer(response.answer, turnId: assistantTurnId)
            await refreshTurns(concept.id)
        } catch {
            turns.removeAll { turn in
                turn.id == assistantTurnId || turn.id == userTurnId
            }
            ConceptLocalStore(modelContext: modelContext).recordFailedFollowUpDraft(
                concept: concept,
                question: question
            )
            errorMessage = error.localizedDescription
        }
        isSubmittingFollowUp = false
    }

    private func appendAssistantDelta(_ delta: String, turnId: UUID) {
        guard let index = turns.firstIndex(where: { $0.id == turnId }) else { return }
        turns[index].content += delta
    }

    private func replaceAssistantAnswer(_ answer: String, turnId: UUID) {
        guard let index = turns.firstIndex(where: { $0.id == turnId }) else { return }
        turns[index].content = answer
    }

    private func restoreFailedFollowUpDraft() {
        guard followUpText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              let concept,
              let draft = ConceptLocalStore(modelContext: modelContext)
                .latestFailedFollowUpDraft(for: concept) else {
            return
        }
        followUpText = draft
        errorMessage = "Previous follow-up was not sent. You can edit and retry it."
    }

    private func refreshConcept(_ conceptId: UUID) async {
        if let concept, ConceptStatusRules.isLocalOnly(concept.captureStatus) {
            return
        }
        guard !isRefreshingConcept else { return }
        isRefreshingConcept = true
        defer {
            isRefreshingConcept = false
        }
        do {
            let concept = try await appServices.apiClient.getConcept(id: conceptId)
            _ = try ConceptLocalStore(modelContext: modelContext).upsertConcept(from: concept)
            refreshOrganization(for: conceptId)
        } catch is CancellationError {
            return
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func refreshTurns(_ conceptId: UUID) async {
        if let concept, ConceptStatusRules.isLocalOnly(concept.captureStatus) {
            turns = ConceptLocalStore(modelContext: modelContext)
                .localConversationTurns(for: concept)
            return
        }
        do {
            let remoteTurns = try await appServices.apiClient.listTurns(conceptId: conceptId)
            if !remoteTurns.isEmpty {
                turns = remoteTurns
            } else if let concept {
                let localTurns = ConceptLocalStore(modelContext: modelContext)
                    .localConversationTurns(for: concept)
                if !localTurns.isEmpty || turns.isEmpty {
                    turns = localTurns
                }
            }
        } catch is CancellationError {
            return
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func mergeProposal(_ proposal: ConceptUpdateProposal) async {
        resolvingProposalId = proposal.id
        errorMessage = nil
        do {
            let concept = try await appServices.apiClient.mergeProposal(id: proposal.id)
            let store = ConceptLocalStore(modelContext: modelContext)
            _ = try store.upsertConcept(from: concept)
            refreshOrganization(for: concept.id)
            try store.markProposal(id: proposal.id, status: .accepted)
        } catch {
            errorMessage = error.localizedDescription
        }
        resolvingProposalId = nil
    }

    private func dismissProposal(_ proposal: ConceptUpdateProposal) async {
        resolvingProposalId = proposal.id
        errorMessage = nil
        do {
            try await appServices.apiClient.dismissProposal(id: proposal.id)
            try ConceptLocalStore(modelContext: modelContext).markProposal(
                id: proposal.id,
                status: .dismissed
            )
        } catch {
            errorMessage = error.localizedDescription
        }
        resolvingProposalId = nil
    }

    private func patchOperations(for proposal: ConceptUpdateProposal) -> [PatchOperationDTO] {
        guard let data = proposal.patchOperationsJSON.data(using: .utf8) else { return [] }
        return (try? JSONDecoder().decode([PatchOperationDTO].self, from: data)) ?? []
    }

    private func source(for turn: ConceptHistoryTurnDTO) -> AnswerSourceDTO? {
        if let answerSource = turn.answerSource {
            return answerSource
        }
        if turn.id == turns.last?.id && turn.role == "assistant" {
            return lastAnswerSource
        }
        return nil
    }

    private func beginSummaryEdit() {
        guard let concept else { return }
        draftTitle = concept.displayTitle
        draftExplanation = concept.oneLineExplanation
        draftTags = conceptTagNames.joined(separator: ", ")
        draftTopics = conceptTopicNames.joined(separator: ", ")
        isEditingSummary = true
    }

    private func saveSummaryEdit() async {
        guard let concept else { return }
        do {
            let store = ConceptLocalStore(modelContext: modelContext)
            let updated = try await appServices.apiClient.updateConceptSummary(
                id: concept.id,
                request: UpdateConceptSummaryRequest(
                    displayTitle: draftTitle,
                    oneLineExplanation: draftExplanation
                )
            )
            _ = try store.upsertConcept(from: updated)
            let organized = try await appServices.apiClient.updateConceptOrganization(
                id: concept.id,
                request: UpdateConceptOrganizationRequest(
                    tags: splitList(draftTags),
                    topics: splitList(draftTopics)
                )
            )
            _ = try store.upsertConcept(from: organized)
            refreshOrganization(for: concept.id)
            isEditingSummary = false
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func beginBlockEdit(_ block: NoteBlock) {
        editingBlockId = block.id
        draftBlockContent = block.content
    }

    private func saveBlockEdit() async {
        guard let blockId = editingBlockId,
              let block = concept?.note?.blocks.first(where: { $0.id == blockId }) else { return }
        do {
            let updated = try await appServices.apiClient.updateNoteBlock(
                conceptId: conceptId,
                blockId: block.id,
                request: UpdateNoteBlockRequest(content: draftBlockContent)
            )
            _ = try ConceptLocalStore(modelContext: modelContext).upsertConcept(from: updated)
            editingBlockId = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func splitList(_ text: String) -> [String] {
        text.split { character in
            character == "," || character == "\n" || character == "，"
        }
        .map(String.init)
    }

    private func refreshOrganization(for conceptId: UUID) {
        do {
            let conceptTags = try modelContext.fetch(FetchDescriptor<ConceptTag>())
                .filter { $0.conceptId == conceptId }
            let tagIds = Set(conceptTags.map(\.tagId))
            conceptTagNames = try modelContext.fetch(FetchDescriptor<Tag>())
                .filter { tagIds.contains($0.id) }
                .map(\.name)
                .sorted { lhs, rhs in
                    lhs.localizedCaseInsensitiveCompare(rhs) == .orderedAscending
                }

            let conceptTopics = try modelContext.fetch(FetchDescriptor<ConceptTopic>())
                .filter { $0.conceptId == conceptId }
            let topicIds = Set(conceptTopics.map(\.topicId))
            conceptTopicNames = try modelContext.fetch(FetchDescriptor<Topic>())
                .filter { topicIds.contains($0.id) }
                .map(\.name)
                .sorted { lhs, rhs in
                    lhs.localizedCaseInsensitiveCompare(rhs) == .orderedAscending
                }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func relatedRelationRows(for concept: Concept) -> [RelatedConceptRowModel] {
        relations.compactMap { relation in
            guard relation.status == "accepted" else { return nil }
            let targetId: UUID
            if relation.sourceConceptId == concept.id {
                targetId = relation.targetConceptId
            } else if relation.targetConceptId == concept.id {
                targetId = relation.sourceConceptId
            } else {
                return nil
            }
            guard let relatedConcept = allConcepts.first(where: { $0.id == targetId }) else {
                return nil
            }
            return RelatedConceptRowModel(relation: relation, concept: relatedConcept)
        }
        .sorted { lhs, rhs in
            lhs.concept.displayTitle.localizedCaseInsensitiveCompare(rhs.concept.displayTitle)
                == .orderedAscending
        }
    }

    private func relatedCandidates(for concept: Concept) -> [Concept] {
        let relatedIds = Set(
            relatedRelationRows(for: concept).map(\.concept.id)
        )
        return allConcepts.filter { candidate in
            candidate.id != concept.id && !relatedIds.contains(candidate.id)
        }
    }

    private func addRelation(from concept: Concept, to target: Concept) async {
        addingRelationTargetId = target.id
        errorMessage = nil
        defer {
            addingRelationTargetId = nil
        }
        do {
            let updated = try await appServices.apiClient.addRelation(
                conceptId: concept.id,
                request: CreateConceptRelationRequest(targetConceptId: target.id)
            )
            _ = try ConceptLocalStore(modelContext: modelContext).upsertConcept(from: updated)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func removeRelation(_ relation: ConceptRelation) async {
        resolvingRelationId = relation.id
        errorMessage = nil
        defer {
            resolvingRelationId = nil
        }
        do {
            let updated = try await appServices.apiClient.removeRelation(
                conceptId: conceptId,
                relationId: relation.id
            )
            _ = try ConceptLocalStore(modelContext: modelContext).upsertConcept(from: updated)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func answerSource(for concept: Concept) -> AnswerSourceDTO? {
        guard let json = concept.answerSourceJSON,
              let data = json.data(using: .utf8) else {
            return nil
        }
        return try? JSONDecoder().decode(AnswerSourceDTO.self, from: data)
    }
}

private struct TurnRow: View {
    var turn: ConceptHistoryTurnDTO
    var isStreaming: Bool = false
    var showSavedChip: Bool = false

    private var isAssistant: Bool {
        turn.role == "assistant"
    }

    var body: some View {
        if isAssistant {
            AssistantMessage(text: turn.content, isStreaming: isStreaming, showSavedChip: showSavedChip)
        } else {
            HStack {
                Spacer(minLength: 44)
                MarkdownText(turn.content)
                    .foregroundStyle(SiftColor.textPrimary)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 11)
                    .background(
                        SiftColor.surfaceSoftHi,
                        in: UnevenRoundedRectangle(
                            topLeadingRadius: 16, bottomLeadingRadius: 16,
                            bottomTrailingRadius: 6, topTrailingRadius: 16,
                            style: .continuous
                        )
                    )
            }
        }
    }
}

private struct AssistantMessage: View {
    var text: String
    var isStreaming: Bool = false
    var showSavedChip: Bool = false

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 7) {
                SiftSymbol(size: 18)
                    .frame(width: 18, height: 18)
                Text("Sift")
                    .font(SiftFont.sans(13, .semibold))
                    .foregroundStyle(SiftColor.textPrimary)
            }

            HStack(alignment: .bottom, spacing: 0) {
                MarkdownText(text)
                    .foregroundStyle(SiftColor.textSecondary)
                if isStreaming {
                    StreamingCaret()
                        .padding(.leading, 2)
                        .padding(.bottom, 3)
                }
            }

            if showSavedChip {
                HStack(spacing: 6) {
                    Image(systemName: "checkmark")
                        .font(.system(size: 10, weight: .bold))
                    Text("Saved to note")
                        .font(SiftFont.sans(12, .medium))
                }
                .foregroundStyle(SiftColor.accentTextOnWash)
                .padding(.horizontal, 10)
                .padding(.vertical, 5)
                .background(SiftColor.accentWash, in: Capsule())
                .overlay(Capsule().strokeBorder(SiftColor.accentBorder, lineWidth: 1))
                .padding(.top, 2)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.vertical, 4)
    }
}

/// Blinking accent caret that trails streaming text (1s steps(1) blink).
private struct StreamingCaret: View {
    @State private var visible = true

    var body: some View {
        RoundedRectangle(cornerRadius: 2, style: .continuous)
            .fill(SiftColor.accent)
            .frame(width: 8, height: 17)
            .opacity(visible ? 1 : 0)
            .task {
                while !Task.isCancelled {
                    visible.toggle()
                    try? await Task.sleep(for: .milliseconds(500))
                }
            }
    }
}

private struct MarkdownText: View {
    var text: String

    init(_ text: String) {
        self.text = text
    }

    private var attributedText: AttributedString {
        (try? AttributedString(
            markdown: text,
            options: AttributedString.MarkdownParsingOptions(interpretedSyntax: .full)
        )) ?? AttributedString(text)
    }

    var body: some View {
        Text(attributedText)
            .font(SiftFont.body)
            .lineSpacing(5)
            .textSelection(.enabled)
    }
}

/// A property row in the concept note: fixed label column + value chips.
private struct PropertyRow<Value: View>: View {
    var icon: String
    var label: String
    @ViewBuilder var value: Value

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            HStack(spacing: 7) {
                Image(systemName: icon)
                    .font(.system(size: 13, weight: .regular))
                    .foregroundStyle(SiftColor.textFaint)
                Text(label)
                    .font(SiftFont.sans(13))
                    .foregroundStyle(SiftColor.textFaint)
            }
            .frame(width: 88, alignment: .leading)

            value
            Spacer(minLength: 0)
        }
    }
}

/// Accent-wash text chip (e.g. Maturity = Growing).
private struct AccentWashChip: View {
    var text: String
    var body: some View {
        Text(text)
            .font(SiftFont.tag)
            .foregroundStyle(SiftColor.accentTextOnWash)
            .padding(.horizontal, 9).padding(.vertical, 4)
            .background(SiftColor.accentWash, in: RoundedRectangle(cornerRadius: SiftRadius.chip, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: SiftRadius.chip, style: .continuous)
                    .strokeBorder(SiftColor.accentBorder, lineWidth: 1)
            )
    }
}

private struct InitialConceptExchange: View {
    var concept: Concept

    private var answerText: String {
        if let blocks = concept.note?.blocks, !blocks.isEmpty {
            return blocks.prefix(2)
                .map(\.content)
                .filter { !$0.isEmpty }
                .joined(separator: "\n\n")
        }
        return concept.oneLineExplanation.isEmpty
            ? "Sift created the first concept card. Ask a follow-up to go deeper."
            : concept.oneLineExplanation
    }

    var body: some View {
        VStack(spacing: 12) {
            syntheticRow(label: "You", text: concept.displayTitle, isAssistant: false)
            syntheticRow(label: "Sift", text: answerText, isAssistant: true)
        }
    }

    private func syntheticRow(label: String, text: String, isAssistant: Bool) -> some View {
        HStack {
            if !isAssistant {
                Spacer(minLength: 32)
            }
            if isAssistant {
                AssistantMessage(text: text)
            } else {
                MarkdownText(text)
                    .foregroundStyle(SiftColor.textPrimary)
                    .lineLimit(10)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 11)
                    .background(
                        SiftColor.surfaceSoftHi,
                        in: UnevenRoundedRectangle(
                            topLeadingRadius: 16, bottomLeadingRadius: 16,
                            bottomTrailingRadius: 6, topTrailingRadius: 16,
                            style: .continuous
                        )
                    )
            }
            if isAssistant {
                Spacer(minLength: 32)
            }
        }
    }
}

private struct SourceLinks: View {
    var source: AnswerSourceDTO

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Label(sourceLabel(source), systemImage: sourceIcon(source))
                .font(.caption)
                .foregroundStyle(.secondary)
            if let freshnessNote = source.freshnessNote, !freshnessNote.isEmpty {
                Text(freshnessNote)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
            if let citations = source.citations {
                ForEach(citations) { citation in
                    if let url = URL(string: citation.url) {
                        Link(destination: url) {
                            Label(citation.title, systemImage: "link")
                                .font(.footnote)
                                .lineLimit(2)
                        }
                    }
                }
            }
        }
        .padding(.top, 4)
    }
}

private struct RelatedConceptRowModel: Identifiable {
    var relation: ConceptRelation
    var concept: Concept

    var id: UUID {
        relation.id
    }
}

private struct RelatedConceptRow: View {
    var row: RelatedConceptRowModel
    var onRemove: () -> Void

    var body: some View {
        HStack(spacing: 12) {
            NavigationLink(value: row.concept.id) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(row.concept.displayTitle)
                        .font(.body.weight(.medium))
                        .foregroundStyle(.primary)
                    Text(row.relation.relationType)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .buttonStyle(.plain)

            Button(action: onRemove) {
                Image(systemName: "xmark")
                    .frame(width: 28, height: 28)
            }
            .buttonStyle(.borderless)
            .accessibilityLabel("Remove related concept")
        }
        .padding(12)
        .background(SiftTheme.elevatedSurface, in: RoundedRectangle(cornerRadius: SiftTheme.compactRadius))
        .overlay {
            RoundedRectangle(cornerRadius: SiftTheme.compactRadius)
                .stroke(SiftTheme.border, lineWidth: 1)
        }
    }
}

private struct SourceNotice: View {
    var source: AnswerSourceDTO

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 8) {
                Label(sourceLabel(source), systemImage: sourceIcon(source))
                Text("\(Int(source.confidence * 100))%")
                    .foregroundStyle(.secondary)
            }
            .font(.caption.weight(.medium))
            .foregroundStyle(.secondary)

            if let uncertaintyNote = source.uncertaintyNote, !uncertaintyNote.isEmpty {
                Text(uncertaintyNote)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
            SourceLinks(source: source)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(10)
        .background(SiftTheme.subtleFill, in: RoundedRectangle(cornerRadius: SiftTheme.compactRadius))
    }
}

private struct ProposalPatchPreview: View {
    var operation: PatchOperationDTO
    var concept: Concept

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Label(title, systemImage: icon)
                .font(.footnote.weight(.medium))
            if let detail {
                Text(detail)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .lineLimit(4)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(10)
        .background(.quaternary.opacity(0.25), in: RoundedRectangle(cornerRadius: 8))
    }

    private var title: String {
        switch operation.operation {
        case "append":
            "Append to \(blockTitle)"
        case "replace":
            "Replace \(blockTitle)"
        case "addRelation":
            "Add related concept"
        default:
            operation.operation
        }
    }

    private var detail: String? {
        switch operation.operation {
        case "append":
            operation.content
        case "replace":
            operation.newContent
        case "addRelation":
            operation.relationType
        default:
            operation.content ?? operation.newContent
        }
    }

    private var icon: String {
        switch operation.operation {
        case "append":
            "text.append"
        case "replace":
            "arrow.triangle.2.circlepath"
        case "addRelation":
            "point.3.connected.trianglepath.dotted"
        default:
            "doc.badge.gearshape"
        }
    }

    private var blockTitle: String {
        guard let targetBlockId = operation.targetBlockId,
              let block = concept.note?.blocks.first(where: { $0.id == targetBlockId }) else {
            return "note"
        }
        switch NoteBlockType(rawValue: block.blockType) {
        case .whatItIs:
            return "What It Is"
        case .whyItMatters:
            return "Why It Matters"
        case .example:
            return "Example"
        case .commonMisunderstandings:
            return "Common Misunderstandings"
        case .relatedConceptsDisplay:
            return "Related Concepts"
        case .userTakeaways:
            return "Takeaways"
        case .none:
            return "note"
        }
    }
}

private func sourceLabel(_ source: AnswerSourceDTO) -> String {
    if source.sourceType == "sourceVerified" || source.sourceType == "webVerified" {
        return "Web"
    }
    if source.sourceType == "searchDiscovered" {
        return "Search"
    }
    if source.sourceType == "userProvided" {
        return "Notes"
    }
    return "Model"
}

private func sourceIcon(_ source: AnswerSourceDTO) -> String {
    if source.sourceType == "sourceVerified" || source.sourceType == "webVerified" {
        return "network"
    }
    if source.sourceType == "searchDiscovered" {
        return "magnifyingglass"
    }
    if source.sourceType == "userProvided" {
        return "doc.text"
    }
    return "sparkles"
}

private struct EditableChipsRow: View {
    var title: String
    var values: [String]
    var emptyText: String
    var icon: String

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Label(title, systemImage: icon)
                .font(.subheadline.weight(.semibold))
            if values.isEmpty {
                Text(emptyText)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            } else {
                FlowChips(values: values)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(SiftTheme.elevatedSurface, in: RoundedRectangle(cornerRadius: SiftTheme.compactRadius))
        .overlay {
            RoundedRectangle(cornerRadius: SiftTheme.compactRadius)
                .stroke(SiftTheme.border, lineWidth: 1)
        }
    }
}

private struct FlowChips: View {
    var values: [String]

    var body: some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: 8) {
                chips
            }
            VStack(alignment: .leading, spacing: 8) {
                chips
            }
        }
    }

    @ViewBuilder private var chips: some View {
        ForEach(values, id: \.self) { value in
            Text(value)
                .font(.caption.weight(.medium))
                .padding(.horizontal, 9)
                .padding(.vertical, 5)
                .background(SiftTheme.subtleFill, in: Capsule())
        }
    }
}

private struct NoteBlockView: View {
    var block: NoteBlock
    var onEdit: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(title(for: block.blockType))
                    .font(.subheadline.weight(.semibold))
                if block.isUserLocked {
                    Image(systemName: "lock")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Button(action: onEdit) {
                    Image(systemName: "pencil")
                }
                .buttonStyle(.borderless)
                .accessibilityLabel("Edit note block")
            }

            Text(block.content)
                .font(.body)
                .foregroundStyle(.primary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(SiftTheme.elevatedSurface, in: RoundedRectangle(cornerRadius: SiftTheme.compactRadius))
        .overlay {
            RoundedRectangle(cornerRadius: SiftTheme.compactRadius)
                .stroke(SiftTheme.border, lineWidth: 1)
        }
    }

    private func title(for blockType: String) -> String {
        switch NoteBlockType(rawValue: blockType) {
        case .whatItIs:
            "What It Is"
        case .whyItMatters:
            "Why It Matters"
        case .example:
            "Example"
        case .commonMisunderstandings:
            "Common Misunderstandings"
        case .relatedConceptsDisplay:
            "Related Concepts"
        case .userTakeaways:
            "Takeaways"
        case .none:
            blockType
        }
    }
}

private struct ConceptSummaryEditor: View {
    @Binding var title: String
    @Binding var explanation: String
    @Binding var tags: String
    @Binding var topics: String
    var onCancel: () -> Void
    var onSave: () -> Void

    var body: some View {
        Form {
            Section("Concept") {
                TextField("Title", text: $title)
                TextField("One-line explanation", text: $explanation, axis: .vertical)
                    .lineLimit(2...5)
            }
            Section("Organization") {
                TextField("Topics", text: $topics, axis: .vertical)
                    .lineLimit(1...3)
                TextField("Tags", text: $tags, axis: .vertical)
                    .lineLimit(1...3)
            }
        }
        .navigationTitle("Edit Concept")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .cancellationAction) {
                Button("Cancel", action: onCancel)
            }
            ToolbarItem(placement: .confirmationAction) {
                Button("Save", action: onSave)
                    .disabled(title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }
    }
}

private struct NoteBlockEditor: View {
    @Binding var content: String
    var onCancel: () -> Void
    var onSave: () -> Void

    var body: some View {
        Form {
            Section("Content") {
                TextEditor(text: $content)
                    .frame(minHeight: 180)
            }
        }
        .navigationTitle("Edit Note")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .cancellationAction) {
                Button("Cancel", action: onCancel)
            }
            ToolbarItem(placement: .confirmationAction) {
                Button("Save", action: onSave)
                    .disabled(content.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }
    }
}

private enum SiftStreamingError: LocalizedError {
    case incomplete

    var errorDescription: String? {
        "The streamed response ended before Sift received the final answer."
    }
}

private extension View {
    func sectionCard() -> some View {
        frame(maxWidth: .infinity, alignment: .leading)
            .siftCard(padding: 14)
    }
}
