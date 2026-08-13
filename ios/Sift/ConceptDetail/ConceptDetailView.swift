import SwiftData
import SwiftUI

enum ConceptDetailMode: Hashable {
    case overview
    case followUp
}

private enum ConceptDetailSheet: String, Identifiable {
    case history
    var id: String { rawValue }
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
    @State private var turns: [ConceptHistoryTurnDTO] = []
    @State private var conceptTagNames: [String] = []
    @State private var conceptTopicNames: [String] = []
    @State private var errorMessage: String?
    @State private var isSubmittingFollowUp = false
    @State private var followUpProgressLabel: String?
    @State private var isRefreshingConcept = false
    @State private var resolvingProposalId: UUID?
    @State private var resolvingRelationId: UUID?
    @State private var addingRelationTargetId: UUID?
    @State private var isEditingSummary = false
    @State private var draftTitle = ""
    @State private var draftExplanation = ""
    @State private var draftTags = ""
    @State private var draftTopics = ""
    @State private var draftNoteBlocks: [EditableNoteBlock] = []
    @State private var draftEditorErrorMessage: String?
    @State private var detailMode: ConceptDetailMode = .overview
    @State private var isReadingOffline = false
    @State private var isRetryingGeneration = false
    @State private var followUpTask: Task<Void, Never>?
    @State private var editingTurnIndex: Int?
    @State private var isPresentingQueryEditor = false
    @State private var queryEditorPreviousDraft = ""
    @State private var presentedSheet: ConceptDetailSheet?
    @State private var maintenanceRunIds: [UUID] = []
    @StateObject private var speechCapture = SpeechCaptureService()
    @FocusState private var isFollowUpFocused: Bool

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
        ConversationTimeline.scrollSignature(for: turns.last)
    }

    private var localConversationSignature: String {
        guard let messages = concept?.conversation?.messages else { return "empty" }
        return messages
            .sorted { $0.createdAt < $1.createdAt }
            .map { "\($0.id.uuidString):\($0.content.count):\($0.updateMode)" }
            .joined(separator: "|")
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
                    ZStack {
                        ScrollView {
                            VStack(alignment: .leading, spacing: 20) {
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
                                        hiddenTurnId: editingQuery?.id,
                                        isSubmitting: isSubmittingFollowUp,
                                        progressLabel: followUpProgressLabel,
                                        isRetryingGeneration: isRetryingGeneration,
                                        onRetryGeneration: { Task { await retryGeneration(concept) } },
                                        onAddAssistantToNote: { turn in
                                            beginNoteEdit(appending: turn.content)
                                        },
                                        onRetryAssistant: { turn in
                                            retryAssistantTurn(turn)
                                        },
                                        onEditUserTurn: { turn in
                                            editAndResend(turn)
                                        }
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
                        .allowsHitTesting(!isPresentingQueryEditor)

                        if let editingQuery {
                            EditingQueryFocusLayer(
                                text: editingQuery.content,
                                onCancel: cancelQueryEditing
                            )
                            .transition(.opacity)
                        }
                    }
                    .onChange(of: detailMode) { _, newValue in
                        guard newValue == .followUp else { return }
                        scrollToConversationBottom(proxy, aggressively: true)
                    }
                    .onChange(of: turns.count) { _, _ in
                        scrollToConversationBottom(proxy)
                    }
                    .onChange(of: lastTurnSignature) { _, _ in
                        scrollToConversationBottom(
                            proxy,
                            streaming: turns.last?.status == "streaming"
                        )
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
        // The concept pill sits at the leading edge (next to Back), GPT-style,
        // and carries the title — so the nav bar has no centered title. It is a
        // toggle: card ⇄ conversation.
        .navigationTitle("")
        .navigationBarTitleDisplayMode(.inline)
        .animation(.spring(response: 0.42, dampingFraction: 0.86), value: detailMode)
        .toolbar {
            if let concept {
                ToolbarItem(placement: .topBarLeading) {
                    conceptAnchorPill(for: concept)
                }
            }
            if concept != nil {
                ToolbarItem(placement: .topBarTrailing) {
                    Menu {
                        Button("Edit card", systemImage: "square.and.pencil") { beginNoteEdit() }
                        Button("Version history", systemImage: "clock.arrow.circlepath") { presentedSheet = .history }
                            .accessibilityIdentifier("concept.history.open")
                    } label: {
                        Image(systemName: "ellipsis.circle")
                    }
                    .accessibilityLabel("Concept actions")
                    .accessibilityIdentifier("concept.actions")
                }
            }
        }
        .sheet(isPresented: $isEditingSummary) {
            NavigationStack {
                ConceptFullNoteEditor(
                    title: $draftTitle,
                    explanation: $draftExplanation,
                    tags: $draftTags,
                    topics: $draftTopics,
                    blocks: $draftNoteBlocks,
                    errorMessage: draftEditorErrorMessage,
                    onCancel: { isEditingSummary = false },
                    onSave: { Task { await saveNoteEdit() } }
                )
            }
        }
        .sheet(item: $presentedSheet) { sheet in
            switch sheet {
            case .history:
                ConceptHistoryView(conceptId: conceptId) { restored in
                    refreshOrganization(for: restored.id)
                }
            }
        }
        .task(id: conceptId) {
            concept?.lastViewedAt = .now
            await refreshConcept(conceptId)
            refreshOrganization(for: conceptId)
            await refreshTurns(conceptId)
            await refreshProposals(conceptId)
            restoreFailedFollowUpDraft()
        }
        .task(id: maintenanceRunIds) {
            await observeMaintenanceRuns(maintenanceRunIds, conceptId: conceptId)
        }
        .onChange(of: localConversationSignature) { _, _ in
            syncLocalInitialTurnsIfNeeded()
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
                beginNoteEdit()
            }
        )
    }

    /// Leading concept pill in the nav bar (GPT model-selector style). Sized and
    /// glassed to sit alongside the Back / Edit buttons. Toggles card ⇄ chat.
    private func conceptAnchorPill(for concept: Concept) -> some View {
        Button {
            withAnimation(.spring(response: 0.42, dampingFraction: 0.86)) {
                detailMode = (detailMode == .followUp) ? .overview : .followUp
            }
        } label: {
            HStack(spacing: 5) {
                if activeProposal != nil {
                    Circle()
                        .fill(SiftColor.accent)
                        .frame(width: 6, height: 6)
                }
                Text(pillTitle(concept.displayTitle))
                    .font(SiftFont.sans(15, .semibold))
                    .foregroundStyle(SiftColor.textPrimary)
                    .lineLimit(1)
                Image(systemName: "chevron.down")
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(SiftColor.textFaint)
                    .rotationEffect(.degrees(detailMode == .followUp ? 180 : 0))
            }
            // Leading toolbar items get a tight width proposal; size to content
            // so the title isn't squeezed out (it's pre-capped by pillTitle). No
            // custom background — the system applies the same glass as the
            // Back / Edit buttons, so the text sits in one consistent component.
            .fixedSize(horizontal: true, vertical: false)
        }
        .accessibilityLabel(detailMode == .followUp ? "Show concept card" : "Show conversation")
    }

    /// Cap the pill title so it never crowds the Edit button.
    private func pillTitle(_ title: String) -> String {
        title.count > 16 ? String(title.prefix(15)).trimmingCharacters(in: .whitespaces) + "…" : title
    }

    private func scrollToConversationBottom(
        _ proxy: ScrollViewProxy,
        aggressively: Bool = false,
        streaming: Bool = false
    ) {
        guard detailMode == .followUp else { return }
        if streaming {
            proxy.scrollTo("conversation-bottom", anchor: .bottom)
            return
        }
        withAnimation(aggressively ? nil : .easeOut(duration: 0.22)) {
            proxy.scrollTo("conversation-bottom", anchor: .bottom)
        }
        Task { @MainActor in
            try? await Task.sleep(for: .milliseconds(60))
            withAnimation(.easeOut(duration: 0.22)) {
                proxy.scrollTo("conversation-bottom", anchor: .bottom)
            }
            guard aggressively else { return }
            try? await Task.sleep(for: .milliseconds(180))
            withAnimation(.easeOut(duration: 0.18)) {
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
        HStack(alignment: .center, spacing: 10) {
            Image(systemName: "plus.circle")
                .font(.system(size: 24, weight: .regular))
                .foregroundStyle(SiftColor.textMuted)
                .frame(width: 36, height: 36)

            TextField(
                "",
                text: $followUpText,
                prompt: Text("Reply to Sift…").foregroundColor(SiftColor.textFaint),
                axis: .vertical
            )
            .textFieldStyle(.plain)
            .font(SiftFont.body)
            .foregroundStyle(SiftColor.textPrimary)
            .tint(SiftColor.accent)
            .lineLimit(1...4)
            .frame(minHeight: 36, alignment: .center)
            .focused($isFollowUpFocused)
            .accessibilityIdentifier("concept.composer.input")

            Button {
                Task {
                    await toggleFollowUpSpeechCapture()
                }
            } label: {
                Image(systemName: speechCapture.isRecording ? "mic.fill" : "mic")
                    .font(.system(size: 17, weight: .regular))
                    .frame(width: 28, height: 36)
            }
            .buttonStyle(.plain)
            .foregroundStyle(
                speechCapture.isRecording ? SiftColor.accent : SiftColor.textMuted
            )
            .disabled(isSubmittingFollowUp)
            .accessibilityLabel(
                speechCapture.isRecording ? "Stop voice input" : "Start voice input"
            )
            .accessibilityIdentifier("concept.composer.voice")

            Button {
                if isSubmittingFollowUp {
                    followUpTask?.cancel()
                } else if let concept {
                    withAnimation(.spring(response: 0.42, dampingFraction: 0.86)) {
                        detailMode = .followUp
                    }
                    followUpTask = Task {
                        await submitFollowUp(for: concept)
                        followUpTask = nil
                    }
                }
            } label: {
                Image(systemName: isSubmittingFollowUp ? "stop.fill" : "arrow.up")
                    .font(.system(size: isSubmittingFollowUp ? 11 : 16, weight: .bold))
                    .foregroundStyle(.white)
                    .frame(width: 36, height: 36)
                    .background(
                        composerActionColor,
                        in: Circle()
                    )
                    .contentShape(Circle())
            }
            .buttonStyle(.plain)
            .disabled(!isSubmittingFollowUp && !canSubmitFollowUp)
            .accessibilityLabel(isSubmittingFollowUp ? "Stop response" : "Submit follow-up")
            .accessibilityIdentifier("concept.composer.action")
        }
        .padding(.leading, 10)
        .padding(.trailing, 6)
        .padding(.vertical, 6)
        .background { composerGlassBackground }
        .overlay {
            RoundedRectangle(cornerRadius: 25, style: .continuous)
                .strokeBorder(SiftColor.hairline, lineWidth: 1)
        }
        .shadow(color: .black.opacity(0.07), radius: 12, y: 4)
        .padding(.horizontal, 18)
        .padding(.bottom, SiftLayout.tabBarClearance)
    }

    @ViewBuilder
    private var composerGlassBackground: some View {
        if #available(iOS 26.0, *) {
            Color.clear
                .glassEffect(.regular, in: .rect(cornerRadius: 25))
        } else {
            RoundedRectangle(cornerRadius: 25, style: .continuous)
                .fill(.regularMaterial)
        }
    }

    private var composerActionColor: Color {
        if isSubmittingFollowUp { return SiftColor.accent }
        return SiftColor.accent.opacity(canSubmitFollowUp ? 1 : 0.28)
    }

    // MARK: - Follow-up submission

    private func submitFollowUp(for concept: Concept, question overrideQuestion: String? = nil) async {
        guard !isSubmittingFollowUp else { return }
        speechCapture.stop()
        let question = (overrideQuestion ?? followUpText).trimmingCharacters(in: .whitespacesAndNewlines)
        guard !question.isEmpty else { return }

        isSubmittingFollowUp = true
        followUpProgressLabel = "Preparing card memory"
        defer {
            isSubmittingFollowUp = false
            followUpProgressLabel = nil
        }
        errorMessage = nil
        followUpText = ""
        withAnimation(.spring(response: 0.42, dampingFraction: 0.86)) {
            detailMode = .followUp
        }
        let userTurnId = UUID()
        let assistantTurnId = UUID()
        let replacementIndex = editingTurnIndex.flatMap { turns.indices.contains($0) ? $0 : nil }
        let shouldRestoreQueryEditorOnFailure = isPresentingQueryEditor
        withAnimation(.spring(response: 0.36, dampingFraction: 0.88)) {
            isPresentingQueryEditor = false
        }
        isFollowUpFocused = false
        let replacementBaselineRevision = concept.noteRevision
        let replacedTail: [ConceptHistoryTurnDTO]
        if let replacementIndex {
            replacedTail = Array(turns[replacementIndex...])
            turns.removeSubrange(replacementIndex...)
        } else {
            replacedTail = []
        }
        turns.append(ConceptHistoryTurnDTO(id: userTurnId, role: "user", content: question, status: "completed"))
        turns.append(ConceptHistoryTurnDTO(id: assistantTurnId, role: "assistant", content: "", status: "streaming"))
        // Reserve a per-action idempotency key. A retry of the same question
        // reuses the key while in-flight, so a network-interrupted send doesn't
        // double-write; a terminal failure releases it (see catch).
        let store = ConceptLocalStore(modelContext: modelContext)
        let operationKey = store.reserveFollowUpOperation(concept: concept, question: question)
        var activeRunID: UUID?
        do {
            try modelContext.save()
            var finalResponse: ConceptTurnResponse?
            var completedRun: ModelRunDTO?
            var textSmoother = StreamingTextSmoother { fragment in
                appendAssistantDelta(fragment, turnId: assistantTurnId)
            }
            defer { textSmoother.cancel() }
            for try await event in appServices.apiClient.streamTurn(
                conceptId: concept.id,
                request: ConceptTurnRequest(
                    question: question,
                    replacingTurnIndex: replacementIndex
                ),
                idempotencyKey: operationKey
            ) {
                if let run = event.modelRun {
                    activeRunID = run.id
                    try store.upsertModelRun(run, lastSequence: event.sequence)
                    if run.status == "succeeded" {
                        completedRun = run
                    }
                }
                if event.type == "reset" {
                    textSmoother.cancel()
                    resetAssistantStream(turnId: assistantTurnId)
                    textSmoother = StreamingTextSmoother { fragment in
                        appendAssistantDelta(fragment, turnId: assistantTurnId)
                    }
                }
                if let delta = event.delta, !delta.isEmpty {
                    textSmoother.append(delta)
                }
                if let citations = event.citations, !citations.isEmpty {
                    updateAssistantSources(citations, turnId: assistantTurnId)
                }
                if let progressLabel = event.progressLabel {
                    followUpProgressLabel = progressLabel
                    // After the answer text has started flowing, later progress
                    // steps ("Checking card update", "Saving answer") mean the
                    // streamed answer is finished. Flip it out of the streaming
                    // state now so the message doesn't appear frozen while the
                    // backend runs its structured-generation step.
                    if let index = turns.firstIndex(where: { $0.id == assistantTurnId }),
                       turns[index].status == "streaming",
                       !turns[index].content.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                        turns[index].status = "completed"
                    }
                }
                if let response = event.response {
                    finalResponse = response
                }
            }
            try await textSmoother.finish()
            try Task.checkCancellation()
            guard let response = finalResponse else {
                throw SiftStreamingError.incomplete
            }
            if replacementIndex == 0,
               !InitialQueryReplacement.isApplied(
                   previousRevision: replacementBaselineRevision,
                   responseRevision: response.concept.noteRevision
               ) {
                throw SiftStreamingError.initialReplacementNotApplied
            }
            let updatedConcept = try store.upsertConcept(from: response.concept)
            refreshOrganization(for: response.concept.id)
            if let proposal = response.proposal {
                _ = try store.upsertProposal(proposal, conceptId: response.concept.id)
            }
            store.clearFailedFollowUpDrafts(for: concept, matching: question)
            store.clearFollowUpOperation(concept: concept, key: operationKey)
            // Terminal-only streams (e.g. an idempotent retry) carry no deltas;
            // fall back to the authoritative final answer so no blank bubble remains.
            let streamed = turns.first(where: { $0.id == assistantTurnId })?.content ?? ""
            let streamedSource = turns.first(where: { $0.id == assistantTurnId })?.answerSource
            var finalAnswerSource = response.answerSource
            if finalAnswerSource.citations?.isEmpty != false,
               let streamedSource,
               streamedSource.citations?.isEmpty == false {
                finalAnswerSource.citations = streamedSource.citations
            }
            replaceAssistantAnswer(
                ConversationTimeline.resolvedAssistantContent(streamed: streamed, finalAnswer: response.answer),
                turnId: assistantTurnId,
                answerSource: finalAnswerSource
            )
            followUpProgressLabel = nil
            if replacementIndex == 0 {
                store.replaceInitialExchange(
                    concept: updatedConcept,
                    question: question,
                    answer: response.answer
                )
            }
            editingTurnIndex = nil
            queryEditorPreviousDraft = ""
            companion?.noteSuccess()
            isReadingOffline = false
            maintenanceRunIds = completedRun?.childRunIds ?? []
        } catch is CancellationError {
            if let activeRunID {
                _ = await Task {
                    try? await appServices.apiClient.cancelModelRun(id: activeRunID)
                }.value
            }
            if let replacementIndex {
                turns.removeAll { $0.id == assistantTurnId || $0.id == userTurnId }
                turns.insert(contentsOf: replacedTail, at: min(replacementIndex, turns.count))
                followUpText = question
                if shouldRestoreQueryEditorOnFailure {
                    restoreQueryEditor(afterFailureAt: replacementIndex)
                }
            } else if let index = turns.firstIndex(where: { $0.id == assistantTurnId }) {
                if turns[index].content.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    turns.remove(at: index)
                } else {
                    turns[index].status = "completed"
                }
            }
        } catch {
            // Remove the optimistic bubbles (no blank assistant left behind),
            // persist the draft, restore the composer text, and show a quiet,
            // sanitized hint — never the raw error.
            turns.removeAll { turn in
                turn.id == assistantTurnId || turn.id == userTurnId
            }
            if let replacementIndex {
                turns.insert(contentsOf: replacedTail, at: min(replacementIndex, turns.count))
                if shouldRestoreQueryEditorOnFailure {
                    restoreQueryEditor(afterFailureAt: replacementIndex)
                }
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
    }

    private func toggleFollowUpSpeechCapture() async {
        if speechCapture.isRecording {
            speechCapture.stop()
            return
        }

        do {
            try await speechCapture.start { transcript in
                followUpText = transcript
            }
        } catch {
            errorMessage = "Sift couldn’t start voice input."
        }
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

    private func resetAssistantStream(turnId: UUID) {
        guard let index = turns.firstIndex(where: { $0.id == turnId }) else { return }
        turns[index].content = ""
        turns[index].status = "streaming"
    }

    private func updateAssistantSources(_ citations: [CitationDTO], turnId: UUID) {
        guard let index = turns.firstIndex(where: { $0.id == turnId }) else { return }
        turns[index].answerSource = AnswerSourceDTO(
            sourceType: AnswerSourceType.searchDiscovered.rawValue,
            confidence: 1,
            uncertaintyNote: nil,
            retrievalUsed: true,
            citations: citations
        )
    }

    private func replaceAssistantAnswer(
        _ answer: String,
        turnId: UUID,
        answerSource: AnswerSourceDTO? = nil
    ) {
        guard let index = turns.firstIndex(where: { $0.id == turnId }) else { return }
        if turns[index].content != answer {
            turns[index].content = answer
        }
        turns[index].status = "completed"
        if let answerSource {
            turns[index].answerSource = answerSource
        }
    }

    private func retryAssistantTurn(_ turn: ConceptHistoryTurnDTO) {
        guard !isSubmittingFollowUp,
              let concept,
              let index = turns.firstIndex(where: { $0.id == turn.id }),
              let userIndex = turns[..<index].lastIndex(where: { $0.role == ConversationRole.user.rawValue })
        else {
            return
        }
        let question = turns[userIndex].content
        editingTurnIndex = userIndex
        followUpTask = Task {
            await submitFollowUp(for: concept, question: question)
            followUpTask = nil
        }
    }

    private func editAndResend(_ turn: ConceptHistoryTurnDTO) {
        guard let index = turns.firstIndex(where: { $0.id == turn.id }) else { return }
        withAnimation(.spring(response: 0.36, dampingFraction: 1)) {
            queryEditorPreviousDraft = followUpText
            followUpText = turn.content
            editingTurnIndex = index
            detailMode = .followUp
            isPresentingQueryEditor = true
            isFollowUpFocused = true
        }
    }

    private var editingQuery: ConceptHistoryTurnDTO? {
        guard isPresentingQueryEditor,
              let editingTurnIndex,
              turns.indices.contains(editingTurnIndex),
              turns[editingTurnIndex].role == ConversationRole.user.rawValue else {
            return nil
        }
        return turns[editingTurnIndex]
    }

    private func cancelQueryEditing() {
        withAnimation(.spring(response: 0.36, dampingFraction: 1)) {
            isPresentingQueryEditor = false
            editingTurnIndex = nil
            followUpText = queryEditorPreviousDraft
            queryEditorPreviousDraft = ""
            isFollowUpFocused = false
        }
    }

    private func restoreQueryEditor(afterFailureAt index: Int) {
        guard turns.indices.contains(index) else { return }
        editingTurnIndex = index
        withAnimation(.spring(response: 0.36, dampingFraction: 1)) {
            isPresentingQueryEditor = true
            isFollowUpFocused = true
        }
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

    private func syncLocalInitialTurnsIfNeeded() {
        guard let concept else { return }
        let localInitial = ConversationTimeline.initialExchange(
            from: concept.conversation?.messages ?? []
        )
        guard !localInitial.isEmpty else { return }
        if ConceptStatusRules.isLocalOnly(concept.captureStatus) || turns.isEmpty {
            turns = localInitial
        }
    }

    // MARK: - Proposals

    private func observeMaintenanceRuns(_ runIds: [UUID], conceptId: UUID) async {
        guard !runIds.isEmpty else { return }
        let store = ConceptLocalStore(modelContext: modelContext)
        do {
            try await ConceptMaintenanceObserver(apiClient: appServices.apiClient).observe(
                runIds: runIds
            ) { run, lastSequence in
                try store.upsertModelRun(run, lastSequence: lastSequence)
                try modelContext.save()
            }
            await refreshProposals(conceptId)
        } catch is CancellationError {
            return
        } catch {
            // Maintenance remains recoverable through persisted ModelRuns and the next page load.
            companion?.note(error)
        }
    }

    private func refreshProposals(_ conceptId: UUID) async {
        do {
            let remote = try await appServices.apiClient.listProposals(
                conceptId: conceptId,
                status: .proposed
            )
            try ConceptLocalStore(modelContext: modelContext).reconcileProposedProposals(
                remote,
                conceptId: conceptId
            )
            try modelContext.save()
        } catch is CancellationError {
            return
        } catch {
            // Passive refresh: keep the locally persisted proposal visible while offline.
        }
    }

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
        if case SiftAPIError.modelRunFailed = error { return true }
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

    private func beginNoteEdit(appending appendedContent: String? = nil) {
        guard let concept else { return }
        draftTitle = concept.displayTitle
        draftExplanation = concept.oneLineExplanation
        draftTags = conceptTagNames.joined(separator: ", ")
        draftTopics = conceptTopicNames.joined(separator: ", ")
        draftNoteBlocks = editableBlocks(for: concept)
        draftEditorErrorMessage = nil
        if let appendedContent = appendedContent?.trimmingCharacters(in: .whitespacesAndNewlines),
           !appendedContent.isEmpty {
            draftNoteBlocks.append(
                EditableNoteBlock(
                    blockType: NoteBlockType.userTakeaways.rawValue,
                    content: appendedContent,
                    position: draftNoteBlocks.count
                )
            )
        }
        isEditingSummary = true
    }

    private func saveNoteEdit() async {
        guard let concept else { return }
        do {
            let store = ConceptLocalStore(modelContext: modelContext)
            let requestBlocks = draftNoteBlocks
                .filter { !$0.content.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
                .map(\.request)
            let updated = try await appServices.apiClient.updateConceptNote(
                id: concept.id,
                request: UpdateConceptNoteRequest(
                    displayTitle: draftTitle,
                    oneLineExplanation: draftExplanation,
                    blocks: requestBlocks,
                    tags: splitList(draftTags),
                    topics: splitList(draftTopics)
                )
            )
            _ = try store.upsertConcept(from: updated)
            refreshOrganization(for: concept.id)
            isEditingSummary = false
        } catch {
            draftEditorErrorMessage = "Sift couldn’t save that note. Your edits are still here; try saving again."
            companion?.note(error)
        }
    }

    private func editableBlocks(for concept: Concept) -> [EditableNoteBlock] {
        (concept.note?.blocks ?? [])
            .enumerated()
            .sorted { lhs, rhs in
                let lhsPosition = lhs.element.position ?? lhs.offset
                let rhsPosition = rhs.element.position ?? rhs.offset
                if lhsPosition == rhsPosition {
                    return lhs.offset < rhs.offset
                }
                return lhsPosition < rhsPosition
            }
            .map { offset, block in
                EditableNoteBlock(block: block, fallbackPosition: offset)
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
