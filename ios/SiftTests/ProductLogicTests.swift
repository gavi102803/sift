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
}
