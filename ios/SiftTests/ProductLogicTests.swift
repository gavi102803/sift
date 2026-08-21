import SwiftData
import XCTest
@testable import Sift

final class ProductLogicTests: XCTestCase {

    func testConceptRouteKeepsNavigationIdentityWhenAuthoritativeConceptChanges() {
        let routeId = UUID()
        let draftId = UUID()
        let remoteId = UUID()
        let original = ConceptRoute(
            conceptId: draftId,
            initialMode: .followUp,
            routeId: routeId
        )
        let navigationPath = Set([original])
        original.conceptId = remoteId

        XCTAssertTrue(navigationPath.contains(original))
        XCTAssertEqual(original.conceptId, remoteId)
    }

    @MainActor
    func testStreamingTextSmootherRevealsNetworkChunksInSmallOrderedFragments() async throws {
        var fragments: [String] = []
        let smoother = StreamingTextSmoother(
            charactersPerTick: 4,
            tickInterval: .zero,
            sleeper: { _ in },
            onFragment: { fragments.append($0) }
        )

        smoother.append("abcdefgh")
        smoother.append("中文流式输出")
        try await smoother.finish()

        XCTAssertEqual(fragments, ["abcd", "efgh", "中文流式", "输出"])
        XCTAssertEqual(fragments.joined(), "abcdefgh中文流式输出")
    }

    @MainActor
    func testStreamingTextSmootherAcceptsMoreNetworkDataWhilePresentationIsSleeping() async throws {
        let sleepStarted = expectation(description: "presentation sleep started")
        sleepStarted.assertForOverFulfill = false
        let releaseSleep = AsyncStream<Void>.makeStream()
        var fragments: [String] = []
        let smoother = StreamingTextSmoother(
            charactersPerTick: 4,
            tickInterval: .milliseconds(24),
            sleeper: { _ in
                sleepStarted.fulfill()
                for await _ in releaseSleep.stream.prefix(1) {}
            },
            onFragment: { fragments.append($0) }
        )

        smoother.append("abcdefgh")
        await fulfillment(of: [sleepStarted], timeout: 1)
        smoother.append("ijkl")
        releaseSleep.continuation.yield()
        releaseSleep.continuation.yield()
        releaseSleep.continuation.finish()
        try await smoother.finish()

        XCTAssertEqual(fragments.joined(), "abcdefghijkl")
    }

    func testArchiveSelectionPlanSeparatesLocalDraftsFromBackendConcepts() {
        let ready = Concept(
            canonicalTitle: "Ready",
            displayTitle: "Ready",
            captureStatus: CaptureStatus.ready.rawValue
        )
        let review = Concept(
            canonicalTitle: "Review",
            displayTitle: "Review",
            captureStatus: CaptureStatus.needsDisambiguation.rawValue
        )
        let failed = Concept(
            canonicalTitle: "Failed",
            displayTitle: "Failed",
            captureStatus: CaptureStatus.generationFailed.rawValue
        )

        let plan = ConceptArchiveSelectionPlan(concepts: [ready, review, failed])

        XCTAssertEqual(Set(plan.remoteConceptIds), [ready.id])
        XCTAssertEqual(Set(plan.localDraftIds), [review.id, failed.id])
        XCTAssertEqual(plan.totalCount, 3)
        XCTAssertEqual(plan.confirmationTitle, "Delete 3 selected items?")
        XCTAssertEqual(plan.confirmationActionTitle, "Move Cards and Discard Drafts")
        XCTAssertTrue(plan.confirmationMessage.contains("permanently discarded"))
    }

    func testLocalDraftArchivePlanNeverCreatesBackendWork() {
        let draft = Concept(
            canonicalTitle: "Unfinished",
            displayTitle: "Unfinished",
            captureStatus: CaptureStatus.needsDisambiguation.rawValue
        )

        let plan = ConceptArchiveSelectionPlan(concepts: [draft])

        XCTAssertTrue(plan.remoteConceptIds.isEmpty)
        XCTAssertEqual(plan.localDraftIds, [draft.id])
        XCTAssertEqual(plan.confirmationTitle, "Discard 1 unfinished draft?")
        XCTAssertEqual(plan.confirmationActionTitle, "Discard Draft")
        XCTAssertTrue(plan.confirmationMessage.contains("cannot be restored"))
    }

    func testBackendFailedConceptIsArchivedRemotely() {
        let failed = Concept(
            canonicalTitle: "Failed remotely",
            displayTitle: "Failed remotely",
            captureStatus: CaptureStatus.generationFailed.rawValue
        )

        let plan = ConceptArchiveSelectionPlan(
            concepts: [failed],
            backendConceptIds: [failed.id]
        )

        XCTAssertEqual(plan.remoteConceptIds, [failed.id])
        XCTAssertTrue(plan.localDraftIds.isEmpty)
        XCTAssertEqual(plan.confirmationActionTitle, "Move to Recently Deleted")
    }

    func testUnknownFailedConceptRequiresBackendRefreshBeforeDeletion() {
        let failed = Concept(
            canonicalTitle: "Failed remotely",
            displayTitle: "Failed remotely",
            captureStatus: CaptureStatus.generationFailed.rawValue
        )
        let review = Concept(
            canonicalTitle: "Local review",
            displayTitle: "Local review",
            captureStatus: CaptureStatus.needsDisambiguation.rawValue
        )

        XCTAssertTrue(
            ConceptArchiveSelectionPlan.requiresBackendRefresh(
                concepts: [failed],
                backendConceptIds: []
            )
        )
        XCTAssertTrue(
            ConceptArchiveSelectionPlan.requiresBackendRefresh(
                concepts: [failed],
                backendConceptIds: [failed.id]
            )
        )
        XCTAssertFalse(
            ConceptArchiveSelectionPlan.requiresBackendRefresh(
                concepts: [review],
                backendConceptIds: []
            )
        )
    }

    func testBatchConceptRequestUsesCanonicalLowercaseUUIDStrings() throws {
        let id = try XCTUnwrap(UUID(uuidString: "9987c5e5-a3ea-48a4-9391-cbcf32a5b6cb"))
        let request = BatchConceptRequest(conceptIds: [id])
        let data = try JSONEncoder().encode(request)
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: [String]])

        XCTAssertEqual(object["conceptIds"], ["9987c5e5-a3ea-48a4-9391-cbcf32a5b6cb"])
    }

    func testCitationMarkupReplacesRetrievalPositionsWithSourceTitles() {
        let citations = [
            CitationDTO(
                sourceId: "3f2ab7e0-0000-4xxx-yyyy-000000000001",
                title: "Agent Client Protocol",
                url: "https://example.com/acp"
            ),
            CitationDTO(
                sourceId: "3f2ab7e0-0000-4xxx-yyyy-000000000002",
                title: "ACP Documentation",
                url: "https://example.com/docs"
            )
        ]

        let blocks = CitationMarkup.blocks(
            in: "ACP standardizes agent communication [1][2].",
            citations: citations
        )

        XCTAssertEqual(blocks.count, 1)
        XCTAssertEqual(blocks[0].text, "ACP standardizes agent communication.")
        XCTAssertEqual(blocks[0].citations.map(\.title), ["Agent Client Protocol", "ACP Documentation"])
    }

    func testCitationMarkupRemovesUnknownNumericReferences() {
        let citation = CitationDTO(
            sourceId: "3f2ab7e0-0000-4xxx-yyyy-000000000001",
            title: "Agent Client Protocol",
            url: "https://example.com/acp"
        )

        let blocks = CitationMarkup.blocks(in: "Known [1], stale [9].", citations: [citation])

        XCTAssertEqual(blocks[0].text, "Known, stale.")
        XCTAssertEqual(blocks[0].citations.map(\.title), ["Agent Client Protocol"])
    }

    func testCitationMarkupRemovesBareMarkersWithoutCitationMetadata() {
        let blocks = CitationMarkup.blocks(
            in: "ACP is an agent protocol [3].",
            citations: []
        )

        XCTAssertEqual(blocks[0].text, "ACP is an agent protocol.")
        XCTAssertTrue(blocks[0].citations.isEmpty)
    }

    func testPersistedCardCopyRemovesMarkersWithoutRenderingSources() {
        XCTAssertEqual(
            CitationMarkup.removingMarkers(from: "ACP is standardized [3][5]."),
            "ACP is standardized."
        )
    }

    // MARK: Proposal copy safety

    func testCleanRationaleIsShownVerbatim() {
        let rationale = "Your follow-up clarified how often the answers change."
        XCTAssertTrue(ProposalCopy.isClean(rationale))
        XCTAssertEqual(
            ProposalCopy.userFacingText(rationale: rationale, targetTitle: "What it is"),
            rationale
        )
    }

    func testInternalRationaleIsReplacedWithBlockCopy() {
        let rationale = "Replace primary block due to stale base revision."
        XCTAssertFalse(ProposalCopy.isClean(rationale))
        XCTAssertEqual(
            ProposalCopy.userFacingText(rationale: rationale, targetTitle: "What it is"),
            "Suggested update to “What it is”."
        )
    }

    func testInternalRationaleWithoutTargetFallsBackToGenericCopy() {
        let rationale = "needs_confirmation: patch operation pending."
        XCTAssertEqual(
            ProposalCopy.userFacingText(rationale: rationale, targetTitle: nil),
            "Sift found an update worth reviewing."
        )
    }

    func testEmptyRationaleDegradesGracefully() {
        XCTAssertEqual(
            ProposalCopy.userFacingText(rationale: "  ", targetTitle: "Example"),
            "Suggested update to “Example”."
        )
    }

    // MARK: Reading order

    func testReadingOrderFollowsSavedPositionsAndShowsUnknownBlocks() {
        let blocks = [
            NoteBlock(blockType: NoteBlockType.example.rawValue, content: "ex", position: 2),
            NoteBlock(blockType: NoteBlockType.relatedConceptsDisplay.rawValue, content: "should be skipped"),
            NoteBlock(blockType: "customInsight", content: "custom", position: 0),
            NoteBlock(blockType: NoteBlockType.whatItIs.rawValue, content: "wii", position: 1),
            NoteBlock(blockType: NoteBlockType.whyItMatters.rawValue, content: "  ", position: 3),
            NoteBlock(blockType: NoteBlockType.commonMisunderstandings.rawValue, content: "cm", position: 4)
        ]
        let ordered = ReadingContent.orderedBlocks(blocks).map(\.blockType)
        XCTAssertEqual(ordered, [
            "customInsight",
            NoteBlockType.whatItIs.rawValue,
            NoteBlockType.example.rawValue,
            NoteBlockType.commonMisunderstandings.rawValue
        ])
    }

    // MARK: Provider allowlist

    func testProviderAllowlistHidesMockComingSoonAndUnknown() {
        XCTAssertTrue(ProviderAllowlist.isStandardVisible(provider(id: "deepseek")))
        XCTAssertFalse(ProviderAllowlist.isStandardVisible(provider(id: "mock")))
        XCTAssertFalse(ProviderAllowlist.isStandardVisible(provider(id: "anthropic", status: "comingSoon")))
        XCTAssertFalse(ProviderAllowlist.isStandardVisible(provider(id: "someUpstream")))
    }

    func testStandardVisibleAlwaysIncludesSelectedProvider() {
        let providers = [provider(id: "custom"), provider(id: "deepseek")]
        let visible = ProviderAllowlist.standardVisible(providers, selected: "custom").map(\.id)
        XCTAssertTrue(visible.contains("custom"))
        XCTAssertTrue(visible.contains("deepseek"))
    }

    /// Visibility follows the backend `exposureTier`: plannedStable → standard,
    /// advanced → advanced group, custom → neither (Advanced Connections only).
    func testProviderVisibilityFollowsExposureTier() {
        XCTAssertTrue(ProviderAllowlist.isStandardVisible(provider(id: "kimi-coding", tier: "plannedStable")))
        XCTAssertFalse(ProviderAllowlist.isStandardVisible(provider(id: "nvidia", tier: "advanced")))
        XCTAssertFalse(ProviderAllowlist.isStandardVisible(provider(id: "custom", tier: "plannedStable")))

        XCTAssertTrue(ProviderAllowlist.isAdvancedVisible(provider(id: "nvidia", tier: "advanced")))
        XCTAssertFalse(ProviderAllowlist.isAdvancedVisible(provider(id: "kimi", tier: "plannedStable")))
        XCTAssertFalse(ProviderAllowlist.isAdvancedVisible(provider(id: "custom", tier: "plannedStable")))
    }

    func testAdvancedVisibleExcludesSelectedAndSortsByName() {
        let providers = [
            provider(id: "nvidia", tier: "advanced"),
            provider(id: "huggingface", tier: "advanced"),
            provider(id: "kimi", tier: "plannedStable")
        ]
        let advanced = ProviderAllowlist.advancedVisible(providers, selected: "nvidia").map(\.id)
        XCTAssertEqual(advanced, ["huggingface"]) // nvidia is selected-out; kimi is standard, not advanced
    }

    private func provider(id: String, status: String = "available", tier: String? = nil) -> RuntimeProviderOptionDTO {
        RuntimeProviderOptionDTO(
            id: id,
            name: id.capitalized,
            description: "",
            adapter: "openai_compatible",
            exposureTier: tier,
            defaultBaseURL: "https://example.com/v1",
            defaultModel: "model",
            requiresApiKey: true,
            supportsModelListing: true,
            status: status,
            isAdvanced: id == "custom" || tier == "advanced"
        )
    }

    // MARK: - Conversation timeline reconciliation
    //
    // Authority model: backend conversation history is durable truth; the local
    // initialCapture exchange is an optimistic / offline fallback only.

    /// Capture → the original question must be visible before remote arrives.
    func testCaptureQuestionVisibleBeforeRemoteHistory() {
        let local = ConversationTimeline.initialExchange(from: [
            message(.user, "What is a semantic cache?", LocalConversationMarker.initialCapture, 0)
        ])
        let display = ConversationTimeline.displayTurns(localInitial: local, remote: [])
        XCTAssertEqual(display.map(\.content), ["What is a semantic cache?"])
    }

    /// Once the backend initial exchange arrives it supersedes the local pair —
    /// shown exactly once, even if the assistant wording differs slightly.
    func testBackendInitialExchangeShownOnceDespiteAssistantDrift() {
        let local = [
            turn(.user, "What is a semantic cache?"),
            turn(.assistant, "A cache keyed on meaning.")
        ]
        let remote = [
            turn(.user, "What is a semantic cache?"),
            turn(.assistant, "A cache keyed on the meaning of a request, so similar questions reuse a stored answer.")
        ]
        let display = ConversationTimeline.displayTurns(localInitial: local, remote: remote)
        XCTAssertEqual(display.map(\.content), remote.map(\.content))
        XCTAssertEqual(display.filter { $0.role == "user" && $0.content == "What is a semantic cache?" }.count, 1)
    }

    /// Reopening a card shows only the backend authoritative turns.
    func testReopenShowsBackendAuthoritativeTurnsOnly() {
        let local = [turn(.user, "What is a semantic cache?"), turn(.assistant, "A cache keyed on meaning.")]
        let remote = [
            turn(.user, "What is a semantic cache?"),
            turn(.assistant, "A cache keyed on the meaning of a request."),
            turn(.user, "How is it different from a normal cache?"),
            turn(.assistant, "A normal cache needs an exact key match.")
        ]
        let display = ConversationTimeline.displayTurns(localInitial: local, remote: remote)
        XCTAssertEqual(display.map(\.content), remote.map(\.content))
    }

    /// After a follow-up, the initial exchange must not disappear (the backend
    /// returns it at the head of authoritative history).
    func testInitialExchangeSurvivesFollowUp() {
        let local = [turn(.user, "What is a semantic cache?"), turn(.assistant, "A cache keyed on meaning.")]
        let remote = [
            turn(.user, "What is a semantic cache?"),
            turn(.assistant, "A cache keyed on the meaning of a request."),
            turn(.user, "How is it different from a normal cache?"),
            turn(.assistant, "A normal cache needs an exact key match.")
        ]
        let display = ConversationTimeline.displayTurns(localInitial: local, remote: remote)
        XCTAssertTrue(display.contains { $0.role == "user" && $0.content == "What is a semantic cache?" })
    }

    func testInitialQueryReplacementRequiresARevisionAdvance() {
        XCTAssertFalse(
            InitialQueryReplacement.isApplied(previousRevision: 4, responseRevision: 4)
        )
        XCTAssertTrue(
            InitialQueryReplacement.isApplied(previousRevision: 4, responseRevision: 5)
        )
    }

    /// Defensive: if remote lacks the original question, the whole local pair is
    /// prepended — never split, never per-message text-merged.
    func testRemoteWithoutInitialQuestionPrependsWholeLocalPair() {
        let local = [turn(.user, "What is a semantic cache?"), turn(.assistant, "A cache keyed on meaning.")]
        let remote = [turn(.user, "How is it different from a normal cache?"), turn(.assistant, "Exact key vs meaning.")]
        let display = ConversationTimeline.displayTurns(localInitial: local, remote: remote)
        XCTAssertEqual(display.map(\.content), local.map(\.content) + remote.map(\.content))
    }

    /// A generation failure (failed marker on an assistant message) never becomes
    /// a conversation turn — only the question remains in the initial exchange.
    func testGenerationFailureIsNotAnAssistantTurn() {
        let exchange = ConversationTimeline.initialExchange(from: [
            message(.user, "What is a semantic cache?", LocalConversationMarker.initialCapture, 0),
            message(.assistant, "Generation failed: provider unavailable.", LocalConversationMarker.failed, 1)
        ])
        XCTAssertEqual(exchange.map(\.role), ["user"])
        XCTAssertFalse(exchange.contains { $0.content.contains("Generation failed") })
    }

    /// A failed follow-up draft only restores composer text — it is identified by
    /// the exact failed marker and never appears in the timeline.
    func testFailedFollowUpRestoresComposerOnly() {
        let messages = [
            message(.user, "What is a semantic cache?", LocalConversationMarker.initialCapture, 0),
            message(.user, "my unsent follow-up", LocalConversationMarker.failed, 1)
        ]
        XCTAssertEqual(ConversationTimeline.failedFollowUpDraft(from: messages), "my unsent follow-up")
        XCTAssertEqual(ConversationTimeline.initialExchange(from: messages).map(\.content), ["What is a semantic cache?"])
    }

    // MARK: - Local-first companion + failure-state UX

    /// Failure categories are classified without leaking transport detail.
    func testCompanionErrorKindClassifiesConnectionVsServer() {
        XCTAssertEqual(CompanionErrorKind(URLError(.cannotConnectToHost)), .unreachable)
        XCTAssertEqual(CompanionErrorKind(URLError(.timedOut)), .unreachable)
        XCTAssertEqual(CompanionErrorKind(URLError(.notConnectedToInternet)), .unreachable)
        XCTAssertEqual(CompanionErrorKind(SiftAPIError.httpStatus(502, detail: nil)), .companionError)
        XCTAssertEqual(CompanionErrorKind(SiftAPIError.httpStatus(404, detail: nil)), .requestRejected)
        XCTAssertEqual(CompanionErrorKind(SiftAPIError.invalidResponse), .unknown)
        XCTAssertEqual(CompanionErrorKind(NSError(domain: "x", code: 1)), .unknown)
    }

    /// Copy distinguishes "couldn't reach" from "couldn't finish", and never
    /// echoes raw error text.
    func testCompanionCopyDistinguishesUnreachableFromGeneration() {
        XCTAssertEqual(CompanionCopy.message(for: .unreachable).title, CompanionCopy.unreachableTitle)
        XCTAssertEqual(CompanionCopy.message(for: .companionError).title, CompanionCopy.generationTitle)
        XCTAssertNotEqual(CompanionCopy.hint(for: .unreachable), CompanionCopy.hint(for: .companionError))
    }

    func testCredentialPlaceholderUsesSavedPreviewWhenCatalogHasNone() {
        let preview = CredentialFieldPresentation.preview(
            selectedProviderID: "deepseek",
            savedProviderID: "deepseek",
            savedPreview: "***1234",
            catalogPreview: nil
        )

        XCTAssertEqual(
            CredentialFieldPresentation.placeholder(preview: preview),
            "•••••••••••• ***1234"
        )
        XCTAssertNil(
            CredentialFieldPresentation.preview(
                selectedProviderID: "openai",
                savedProviderID: "deepseek",
                savedPreview: "***1234",
                catalogPreview: nil
            )
        )
    }

    /// Mock and unavailable are never the same surface.
    func testMockAndUnavailableAreDistinguishable() {
        XCTAssertNotEqual(CompanionStatus.mock.developerLabel, CompanionStatus.unavailable.developerLabel)
        XCTAssertTrue(AppServices.preview.usesMockBackend)
        let httpServices = AppServices(apiClient: HTTPSiftAPIClient(baseURL: URL(string: "http://127.0.0.1:8000")!))
        XCTAssertFalse(httpServices.usesMockBackend)
    }

    /// Library distinguishes draft / generating / ready / failed without exposing
    /// model or provider names.
    func testCaptureStatusBadgeDistinguishesStates() {
        XCTAssertNil(CaptureStatusBadge.label(for: CaptureStatus.ready.rawValue))
        XCTAssertEqual(CaptureStatusBadge.label(for: CaptureStatus.generating.rawValue), "Generating")
        XCTAssertEqual(CaptureStatusBadge.label(for: CaptureStatus.draft.rawValue), "Draft")
        XCTAssertEqual(CaptureStatusBadge.label(for: CaptureStatus.generationFailed.rawValue), "Needs retry")
        XCTAssertEqual(CaptureStatusBadge.label(for: CaptureStatus.needsDisambiguation.rawValue), "Needs review")
        XCTAssertFalse(CaptureStatusBadge.subtitle(for: CaptureStatus.generationFailed.rawValue).isEmpty)
    }

    /// A terminal-only stream (completed result, no deltas) resolves to the final
    /// answer — never an empty assistant bubble.
    func testTerminalOnlyStreamResolvesToFinalAnswer() {
        XCTAssertEqual(
            ConversationTimeline.resolvedAssistantContent(streamed: "", finalAnswer: "The full answer."),
            "The full answer."
        )
        // Once visible deltas exist, keep that exact string at the terminal
        // boundary so SwiftUI does not replace the whole rendered answer.
        XCTAssertEqual(
            ConversationTimeline.resolvedAssistantContent(
                streamed: "The streamed answer.",
                finalAnswer: "A differently normalized terminal answer."
            ),
            "The streamed answer."
        )
    }

    func testTerminalStatusChangeDoesNotTriggerAnotherScroll() {
        let id = UUID()
        let streaming = ConceptHistoryTurnDTO(
            id: id,
            role: "assistant",
            content: "The streamed answer.",
            status: "streaming"
        )
        let completed = ConceptHistoryTurnDTO(
            id: id,
            role: "assistant",
            content: "The streamed answer.",
            status: "completed"
        )
        let longer = ConceptHistoryTurnDTO(
            id: id,
            role: "assistant",
            content: "The streamed answer. More.",
            status: "streaming"
        )

        XCTAssertEqual(
            ConversationTimeline.scrollSignature(for: streaming),
            ConversationTimeline.scrollSignature(for: completed)
        )
        XCTAssertNotEqual(
            ConversationTimeline.scrollSignature(for: streaming),
            ConversationTimeline.scrollSignature(for: longer)
        )
    }

    func testStreamingMarkdownUsesTheFinalMarkdownSourceWithOnlyACaretAdded() {
        let markdown = "## Current changes\n\n- **Tracing** is live\n- Use `wrangler dev`"

        XCTAssertEqual(
            MarkdownNormalizer.renderedMarkdown(markdown, streaming: true),
            "\(markdown) ▌"
        )
        XCTAssertEqual(MarkdownNormalizer.renderedMarkdown(markdown, streaming: false), markdown)
    }

    func testMarkdownNormalizerDoesNotBreakBoldLeadInSentence() {
        let markdown = "### Runtime update\n\n**Why it matters:** Python runs inside workerd."

        XCTAssertEqual(MarkdownNormalizer.normalize(markdown), markdown)
    }

    /// A failed capture keeps the user's original question visible (as the
    /// initial-capture user turn) and never renders the failure as an answer.
    func testCaptureFailedKeepsOriginalQuestion() {
        let messages = [
            message(.user, "What is a semantic cache?", LocalConversationMarker.initialCapture, 0),
            message(.assistant, "Generation failed: the provider is unavailable.", LocalConversationMarker.failed, 1)
        ]
        let exchange = ConversationTimeline.initialExchange(from: messages)
        XCTAssertEqual(exchange.map(\.content), ["What is a semantic cache?"])
    }

    private func turn(_ role: ConversationRole, _ content: String) -> ConceptHistoryTurnDTO {
        ConceptHistoryTurnDTO(role: role.rawValue, content: content)
    }

    private func message(_ role: ConversationRole, _ content: String, _ mode: String, _ offset: TimeInterval) -> ConversationMessage {
        ConversationMessage(
            role: role.rawValue,
            content: content,
            createdAt: Date(timeIntervalSince1970: offset),
            updateMode: mode
        )
    }
}
