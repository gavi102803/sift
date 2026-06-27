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

    func testReadingOrderFollowsUnderstandingPriorityAndSkipsDisplayBlock() {
        let blocks = [
            NoteBlock(blockType: NoteBlockType.example.rawValue, content: "ex"),
            NoteBlock(blockType: NoteBlockType.relatedConceptsDisplay.rawValue, content: "should be skipped"),
            NoteBlock(blockType: NoteBlockType.whatItIs.rawValue, content: "wii"),
            NoteBlock(blockType: NoteBlockType.whyItMatters.rawValue, content: "  "),
            NoteBlock(blockType: NoteBlockType.commonMisunderstandings.rawValue, content: "cm")
        ]
        let ordered = ReadingContent.orderedBlocks(blocks).map(\.blockType)
        XCTAssertEqual(ordered, [
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

    private func provider(id: String, status: String = "available") -> RuntimeProviderOptionDTO {
        RuntimeProviderOptionDTO(
            id: id,
            name: id.capitalized,
            description: "",
            adapter: "openai_compatible",
            defaultBaseURL: "https://example.com/v1",
            defaultModel: "model",
            requiresApiKey: true,
            supportsModelListing: true,
            status: status,
            isAdvanced: id == "custom"
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
