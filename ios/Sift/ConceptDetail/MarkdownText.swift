import Foundation
import MarkdownUI
import SwiftUI

/// Renders model / note markdown via MarkdownUI with Sift's typography and
/// colors — proper headings, bullet / numbered lists, fenced code blocks,
/// blockquotes, tables, and thematic breaks, instead of a collapsed `Text`.
///
/// During streaming, render one inline caret outside MarkdownUI. Appending the
/// caret to the Markdown source can make an incomplete document interpret and
/// redraw it in more than one block while deltas arrive.
struct MarkdownText: View {
    private let content: String
    private let streamingCaret: Bool

    init(_ text: String, streamingCaret: Bool = false) {
        self.content = MarkdownNormalizer.normalize(text)
        self.streamingCaret = streamingCaret
    }

    @ViewBuilder
    var body: some View {
        if streamingCaret {
            (Text(streamingText) + Text(" ▌").foregroundColor(SiftColor.accent))
                .font(SiftFont.body)
                .foregroundStyle(SiftColor.textSecondary)
                .lineSpacing(3)
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
        } else {
            Markdown(content)
                .markdownTheme(.sift)
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private var streamingText: AttributedString {
        (try? AttributedString(markdown: content)) ?? AttributedString(content)
    }
}

/// Replaces model-facing numeric citation markers with user-facing source
/// pills while preserving Markdown rendering for the answer itself.
struct CitedMarkdownText: View {
    private let blocks: [CitationTextBlock]

    init(_ text: String, citations: [CitationDTO]) {
        blocks = CitationMarkup.blocks(in: text, citations: citations)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            ForEach(blocks) { block in
                MarkdownText(block.text)

                if !block.citations.isEmpty {
                    ScrollView(.horizontal) {
                        HStack(spacing: 6) {
                            ForEach(block.citations) { citation in
                                InlineCitationPill(citation: citation)
                            }
                        }
                    }
                    .scrollIndicators(.hidden)
                    .padding(.top, -4)
                    .padding(.bottom, 8)
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
    private static let trailingDigitsPattern = try! NSRegularExpression(pattern: #"(\d+)$"#)

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
            let reference = referenceNumber(for: citation, fallback: index + 1)
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

    private static func referenceNumber(for citation: CitationDTO, fallback: Int) -> Int {
        guard let sourceId = citation.sourceId else { return fallback }
        let range = NSRange(sourceId.startIndex..., in: sourceId)
        guard let match = trailingDigitsPattern.firstMatch(in: sourceId, range: range),
              let digitsRange = Range(match.range(at: 1), in: sourceId),
              let number = Int(sourceId[digitsRange])
        else {
            return fallback
        }
        return number
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
        .foregroundStyle(SiftColor.textSecondary)
        .padding(.horizontal, 9)
        .padding(.vertical, 6)
        .frame(maxWidth: 220)
        .background(SiftColor.surfaceSoftHi, in: Capsule())
        .overlay {
            Capsule().strokeBorder(SiftColor.hairline, lineWidth: 1)
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
