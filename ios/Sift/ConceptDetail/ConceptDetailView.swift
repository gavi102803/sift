import SwiftData
import SwiftUI

enum ConceptDetailMode: Hashable {
    case overview
    case followUp
}

struct ConceptDetailView: View {
    @Environment(\.appServices) private var appServices
    @Environment(\.modelContext) private var modelContext
    @Environment(CompanionMonitor.self) private var companion: CompanionMonitor?
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
    @State private var editingBlockTitle = ""
    @State private var draftTitle = ""
    @State private var draftExplanation = ""
    @State private var draftTags = ""
    @State private var draftTopics = ""
    @State private var draftBlockContent = ""
    @State private var detailMode: ConceptDetailMode = .overview
    @State private var isReadingOffline = false
    @State private var isRetryingGeneration = false

    private var conceptId: UUID
    /// Called when a retry produces a concept with a new id, so the navigation
    /// route can follow it. A no-op (and id-stable) once retries are idempotent.
    private var onConceptReplaced: (UUID, UUID) -> Void

    init(
        conceptId: UUID,
        initialMode: ConceptDetailMode = .overview,
        onConceptReplaced: @escaping (UUID, UUID) -> Void = { _, _ in }
    ) {
        self.conceptId = conceptId
        self.onConceptReplaced = onConceptReplaced
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
                            if isRefreshingConcept {
                                ProgressView()
                            }
                            if isReadingOffline {
                                CompanionNotice(text: CompanionCopy.readingOffline, tone: .info)
                            }
                            if let errorMessage {
                                CompanionNotice(text: errorMessage, tone: .warning)
                            }
                            if detailMode == .overview {
                                if let activeProposal {
                                    SuggestedUpdateCard(
                                        concept: concept,
                                        proposal: activeProposal,
                                        isResolving: resolvingProposalId == activeProposal.id,
                                        onConfirm: { Task { await mergeProposal(activeProposal) } },
                                        onKeep: { Task { await dismissProposal(activeProposal) } }
                                    )
                                }
                                readingView(for: concept)
                            } else {
                                ConceptFollowUpView(
                                    concept: concept,
                                    turns: turns,
                                    isSubmitting: isSubmittingFollowUp,
                                    lastAnswerSource: lastAnswerSource,
                                    isRetryingGeneration: isRetryingGeneration,
                                    onRetryGeneration: { Task { await retryGeneration(concept) } }
                                )
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
                        ConceptAnchorBar(
                            concept: concept,
                            hasPendingProposal: activeProposal != nil
                        ) {
                            withAnimation(.spring(response: 0.42, dampingFraction: 0.86)) {
                                detailMode = .overview
                            }
                        }
                        .padding(.horizontal, 18)
                        .padding(.top, 6)
                        .padding(.bottom, 8)
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
        // In follow-up the frosted anchor chip carries the title, so the nav bar
        // stays title-less and background-less for a unified, GPT-style top.
        // Overview keeps the default frosted nav bar so reading content stays
        // legible when it scrolls under the bar.
        .navigationTitle(detailMode == .followUp ? "" : (concept?.displayTitle ?? "Concept"))
        .navigationBarTitleDisplayMode(.inline)
        .toolbarBackground(detailMode == .followUp ? Visibility.hidden : Visibility.automatic, for: .navigationBar)
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
                    onCancel: { isEditingSummary = false },
                    onSave: { Task { await saveSummaryEdit() } }
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
                    title: editingBlockTitle,
                    content: $draftBlockContent,
                    onCancel: { editingBlockId = nil },
                    onSave: { Task { await saveBlockEdit() } }
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

    private func readingView(for concept: Concept) -> some View {
        ConceptReadingView(
            concept: concept,
            tagNames: conceptTagNames,
            topicNames: conceptTopicNames,
            relationRows: relatedRelationRows(for: concept),
            relatedCandidates: relatedCandidates(for: concept),
            relatedDisplayFallback: relatedDisplayFallback(for: concept),
            addRelationDisabled: addingRelationTargetId != nil,
            removeRelationDisabled: resolvingRelationId != nil,
            onAddRelation: { candidate in
                Task { await addRelation(from: concept, to: candidate) }
            },
            onRemoveRelation: { relation in
                Task { await removeRelation(relation) }
            },
            onEditBlock: { block in
                beginBlockEdit(block)
            }
        )
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

    // MARK: - Composer

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

    // MARK: - Follow-up submission

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
        // Reserve a per-action idempotency key. A retry of the same question
        // reuses the key while in-flight, so a network-interrupted send doesn't
        // double-write; a terminal failure releases it (see catch).
        let store = ConceptLocalStore(modelContext: modelContext)
        let operationKey = store.reserveFollowUpOperation(concept: concept, question: question)
        do {
            var finalResponse: ConceptTurnResponse?
            for try await event in appServices.apiClient.streamTurn(
                conceptId: concept.id,
                request: ConceptTurnRequest(question: question),
                idempotencyKey: operationKey
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
            _ = try store.upsertConcept(from: response.concept)
            refreshOrganization(for: response.concept.id)
            if let proposal = response.proposal {
                _ = try store.upsertProposal(proposal, conceptId: response.concept.id)
            }
            store.clearFailedFollowUpDrafts(for: concept, matching: question)
            store.clearFollowUpOperation(concept: concept, key: operationKey)
            lastAnswerSource = response.answerSource
            // Terminal-only streams (e.g. an idempotent retry) carry no deltas;
            // fall back to the authoritative final answer so no blank bubble remains.
            let streamed = turns.first(where: { $0.id == assistantTurnId })?.content ?? ""
            replaceAssistantAnswer(
                ConversationTimeline.resolvedAssistantContent(streamed: streamed, finalAnswer: response.answer),
                turnId: assistantTurnId
            )
            companion?.noteSuccess()
            isReadingOffline = false
            await refreshTurns(concept.id)
        } catch is CancellationError {
            turns.removeAll { $0.id == assistantTurnId || $0.id == userTurnId }
        } catch {
            // Remove the optimistic bubbles (no blank assistant left behind),
            // persist the draft, restore the composer text, and show a quiet,
            // sanitized hint — never the raw error.
            turns.removeAll { turn in
                turn.id == assistantTurnId || turn.id == userTurnId
            }
            store.recordFailedFollowUpDraft(concept: concept, question: question)
            // Terminal (server-rejected) failures release the key so a retry uses
            // a fresh one. Network/unknown failures keep it in-flight so a retry
            // reuses the same key and the backend dedupes.
            if isTerminalFailure(error) {
                store.markFollowUpOperationFailed(concept: concept, question: question, key: operationKey)
            }
            if followUpText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                followUpText = question
            }
            present(error)
        }
        isSubmittingFollowUp = false
    }

    /// Retry a failed initial generation via the existing CaptureFlowService
    /// path. The regenerated concept may have a new id (until retries are
    /// idempotent), so the navigation route is updated to follow it.
    private func retryGeneration(_ concept: Concept) async {
        guard !isRetryingGeneration else { return }
        isRetryingGeneration = true
        errorMessage = nil
        defer { isRetryingGeneration = false }
        let service = CaptureFlowService(
            localStore: ConceptLocalStore(modelContext: modelContext),
            apiClient: appServices.apiClient
        )
        do {
            let regenerated = try await service.retryGeneration(for: concept)
            companion?.noteSuccess()
            isReadingOffline = false
            if regenerated.id != concept.id {
                onConceptReplaced(concept.id, regenerated.id)
            } else {
                await refreshTurns(regenerated.id)
            }
        } catch is CancellationError {
            return
        } catch {
            present(error)
        }
    }

    /// Set a sanitized, user-facing hint and record the failure category. Never
    /// stores a raw error string.
    private func present(_ error: Error) {
        let kind = CompanionErrorKind(error)
        errorMessage = CompanionCopy.hint(for: kind)
        companion?.note(error)
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
        // A failed follow-up draft only restores the composer text — it is never
        // a conversation turn. Read it directly (no conversation is created).
        guard followUpText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              let concept,
              let draft = ConversationTimeline.failedFollowUpDraft(
                from: concept.conversation?.messages ?? []
              ) else {
            return
        }
        followUpText = draft
        errorMessage = "Previous follow-up was not sent. You can edit and retry it."
    }

    // MARK: - Data loading

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
            companion?.noteSuccess()
            isReadingOffline = false
        } catch is CancellationError {
            return
        } catch {
            // Passive read: never block the saved card. Note offline quietly.
            companion?.note(error)
            isReadingOffline = (CompanionErrorKind(error) == .unreachable)
        }
    }

    private func refreshTurns(_ conceptId: UUID) async {
        let localInitial = ConversationTimeline.initialExchange(
            from: concept?.conversation?.messages ?? []
        )
        // Local-only concepts have never synced — show the optimistic exchange.
        if let concept, ConceptStatusRules.isLocalOnly(concept.captureStatus) {
            turns = localInitial
            return
        }
        do {
            let remoteTurns = try await appServices.apiClient.listTurns(conceptId: conceptId)
            // Backend history is authoritative; the local exchange is superseded.
            turns = ConversationTimeline.displayTurns(localInitial: localInitial, remote: remoteTurns)
            companion?.noteSuccess()
            isReadingOffline = false
        } catch is CancellationError {
            return
        } catch {
            // Offline / failed: keep the optimistic exchange visible rather than
            // blanking an unsynced timeline. Stay quiet; this is a passive read.
            if turns.isEmpty {
                turns = localInitial
            }
            companion?.note(error)
            isReadingOffline = (CompanionErrorKind(error) == .unreachable)
        }
    }

    // MARK: - Proposals

    private func mergeProposal(_ proposal: ConceptUpdateProposal) async {
        resolvingProposalId = proposal.id
        errorMessage = nil
        let store = ConceptLocalStore(modelContext: modelContext)
        // Per-proposal idempotency key, reused across retries of the same merge.
        let mergeKey = store.mergeIdempotencyKey(for: proposal)
        do {
            let concept = try await appServices.apiClient.mergeProposal(
                id: proposal.id,
                idempotencyKey: mergeKey
            )
            _ = try store.upsertConcept(from: concept)
            refreshOrganization(for: concept.id)
            try store.markProposal(id: proposal.id, status: .accepted)
            store.markProposalMergeCompleted(proposal)
            companion?.noteSuccess()
        } catch {
            store.markProposalMergeFailed(proposal)
            present(error)
        }
        resolvingProposalId = nil
    }

    /// A terminal failure is one the backend explicitly rejected (an HTTP
    /// status). Network/transport errors are treated as unknown so retries can
    /// safely reuse the same idempotency key.
    private func isTerminalFailure(_ error: Error) -> Bool {
        if case SiftAPIError.httpStatus = error { return true }
        return false
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
            present(error)
        }
        resolvingProposalId = nil
    }

    // MARK: - Editing

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
            present(error)
        }
    }

    private func beginBlockEdit(_ block: NoteBlock) {
        editingBlockId = block.id
        editingBlockTitle = noteBlockTitle(block.blockType)
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
            present(error)
        }
    }

    private func splitList(_ text: String) -> [String] {
        text.split { character in
            character == "," || character == "\n" || character == "，"
        }
        .map(String.init)
    }

    // MARK: - Organization + relations

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
            // Local SwiftData read — not a companion failure; stay silent.
        }
    }

    private func relatedDisplayFallback(for concept: Concept) -> String? {
        let content = concept.note?.blocks
            .first { $0.blockType == NoteBlockType.relatedConceptsDisplay.rawValue }?
            .content
            .trimmingCharacters(in: .whitespacesAndNewlines)
        return (content?.isEmpty == false) ? content : nil
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
            present(error)
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
            present(error)
        }
    }
}
