import SwiftData
import XCTest
@testable import Sift

final class ProductLogicTests: XCTestCase {

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
        XCTAssertFalse(CaptureStatusBadge.subtitle(for: CaptureStatus.generationFailed.rawValue).isEmpty)
    }

    /// A terminal-only stream (completed result, no deltas) resolves to the final
    /// answer — never an empty assistant bubble.
    func testTerminalOnlyStreamResolvesToFinalAnswer() {
        XCTAssertEqual(
            ConversationTimeline.resolvedAssistantContent(streamed: "", finalAnswer: "The full answer."),
            "The full answer."
        )
        // Streamed text is kept only if the final answer is somehow empty.
        XCTAssertEqual(
            ConversationTimeline.resolvedAssistantContent(streamed: "partial", finalAnswer: ""),
            "partial"
        )
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
