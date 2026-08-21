import Foundation
import MarkdownUI
import SwiftUI

/// Renders model / note markdown via MarkdownUI with Sift's typography and
/// colors — proper headings, bullet / numbered lists, fenced code blocks,
/// blockquotes, tables, and thematic breaks, instead of a collapsed `Text`.
///
/// Streaming and completed answers deliberately use the same MarkdownUI
/// renderer so headings, lists, and paragraph spacing do not jump when the
/// terminal event arrives.
struct MarkdownText: View {
    private let content: String

    init(_ text: String, streamingCaret: Bool = false) {
        self.content = MarkdownNormalizer.renderedMarkdown(
            text,
            streaming: streamingCaret
        )
    }

    var body: some View {
        Markdown(content)
            .markdownTheme(.sift)
            .textSelection(.enabled)
            .frame(maxWidth: .infinity, alignment: .leading)
    }

}

/// Replaces model-facing numeric citation markers with user-facing source
/// pills while preserving Markdown rendering for the answer itself.
struct CitedMarkdownText: View {
    private let blocks: [CitationTextBlock]
    private let streamingCaret: Bool

    init(_ text: String, citations: [CitationDTO], streamingCaret: Bool = false) {
        blocks = CitationMarkup.blocks(in: text, citations: citations)
        self.streamingCaret = streamingCaret
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            ForEach(blocks) { block in
                MarkdownText(
                    block.text,
                    streamingCaret: streamingCaret && block.id == blocks.last?.id
                )

                if !block.citations.isEmpty {
                    ScrollView(.horizontal) {
                        HStack(spacing: 6) {
                            ForEach(block.citations) { citation in
                                InlineCitationPill(citation: citation)
                            }
                        }
                    }
                    .scrollIndicators(.hidden)
                    .padding(.top, 4)
                    .padding(.bottom, 10)
                }
            }
        }
    }
}

struct CitationTextBlock: Identifiable {
    var id: Int
    var text: String
    var citations: [CitationDTO]
}

enum CitationMarkup {
    private static let markerPattern = try! NSRegularExpression(pattern: #"[ \t]?\[(\d+)\]"#)

    static func removingMarkers(from text: String) -> String {
        let range = NSRange(text.startIndex..., in: text)
        return markerPattern.stringByReplacingMatches(
            in: text,
            range: range,
            withTemplate: ""
        )
    }

    static func blocks(in text: String, citations: [CitationDTO]) -> [CitationTextBlock] {
        var citationsByReference: [Int: CitationDTO] = [:]
        for (index, citation) in citations.enumerated() {
            // The backend instructs the model to cite by each evidence item's
            // 1-based position (`[1]`, `[2]`, ...), while `sourceId` is an
            // opaque id. Map citations by position so those markers resolve.
            let reference = index + 1
            if citationsByReference[reference] == nil {
                citationsByReference[reference] = citation
            }
        }

        return text.components(separatedBy: "\n\n").enumerated().map { index, rawBlock in
            let range = NSRange(rawBlock.startIndex..., in: rawBlock)
            let matches = markerPattern.matches(in: rawBlock, range: range)
            var seenReferences = Set<Int>()
            let cited = matches.compactMap { match -> CitationDTO? in
                guard let numberRange = Range(match.range(at: 1), in: rawBlock),
                      let number = Int(rawBlock[numberRange]),
                      seenReferences.insert(number).inserted
                else {
                    return nil
                }
                return citationsByReference[number]
            }
            let cleaned = markerPattern
                .stringByReplacingMatches(in: rawBlock, range: range, withTemplate: "")
                .trimmingCharacters(in: .whitespacesAndNewlines)
            return CitationTextBlock(id: index, text: cleaned, citations: cited)
        }
        .filter { !$0.text.isEmpty || !$0.citations.isEmpty }
    }
}

private struct InlineCitationPill: View {
    var citation: CitationDTO

    private var destination: URL? { URL(string: citation.url) }

    var body: some View {
        Group {
            if let destination {
                Link(destination: destination) { label }
            } else {
                label
            }
        }
        .buttonStyle(.plain)
    }

    private var label: some View {
        HStack(spacing: 5) {
            Image(systemName: "link")
                .font(.system(size: 10, weight: .semibold))
            Text(citation.title)
                .font(SiftFont.sans(11, .medium))
                .lineLimit(1)
        }
        .foregroundStyle(SiftColor.accent)
        .padding(.horizontal, 11)
        .padding(.vertical, 7)
        .frame(maxWidth: 240)
        .background {
            Capsule()
                .fill(.thinMaterial)
                .overlay {
                    Capsule().fill(SiftColor.accent.opacity(0.09))
                }
        }
        .overlay {
            Capsule().strokeBorder(SiftColor.accent.opacity(0.22), lineWidth: 0.75)
        }
    }
}

private extension Theme {
    static let sift = Theme.basic
        .text {
            ForegroundColor(SiftColor.textSecondary)
            FontSize(15)
        }
        .strong { FontWeight(.semibold) }
        .link { ForegroundColor(SiftColor.accent) }
        .code {
            FontFamilyVariant(.monospaced)
            FontSize(13.5)
            ForegroundColor(SiftColor.textPrimary)
            BackgroundColor(SiftColor.hairline.opacity(0.6))
        }
        .heading1 { label in
            label
                .markdownMargin(top: 14, bottom: 6)
                .markdownTextStyle {
                    FontWeight(.bold); FontSize(20); ForegroundColor(SiftColor.textPrimary)
                }
        }
        .heading2 { label in
            label
                .markdownMargin(top: 12, bottom: 6)
                .markdownTextStyle {
                    FontWeight(.semibold); FontSize(17); ForegroundColor(SiftColor.textPrimary)
                }
        }
        .heading3 { label in
            label
                .markdownMargin(top: 10, bottom: 4)
                .markdownTextStyle {
                    FontWeight(.semibold); FontSize(15); ForegroundColor(SiftColor.textPrimary)
                }
        }
        .paragraph { label in
            label
                .relativeLineSpacing(.em(0.22))
                .markdownMargin(top: 0, bottom: 10)
        }
        .blockquote { label in
            HStack(spacing: 10) {
                RoundedRectangle(cornerRadius: 1.5, style: .continuous)
                    .fill(SiftColor.hairline)
                    .frame(width: 3)
                label.markdownTextStyle { ForegroundColor(SiftColor.textMuted) }
            }
            .fixedSize(horizontal: false, vertical: true)
            .markdownMargin(top: 4, bottom: 10)
        }
        .codeBlock { configuration in
            configuration.label
                .markdownTextStyle {
                    FontFamilyVariant(.monospaced); FontSize(13)
                }
                .relativeLineSpacing(.em(0.18))
                .padding(12)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(SiftColor.surface)
                .overlay(
                    RoundedRectangle(cornerRadius: 10, style: .continuous)
                        .strokeBorder(SiftColor.hairline, lineWidth: 1)
                )
                .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                .markdownMargin(top: 4, bottom: 10)
        }
        .thematicBreak {
            Rectangle()
                .fill(SiftColor.hairline)
                .frame(height: 1)
                .markdownMargin(top: 6, bottom: 6)
        }
}
