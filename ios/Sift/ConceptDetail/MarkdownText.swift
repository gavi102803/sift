import MarkdownUI
import SwiftUI

/// Renders model / note markdown via MarkdownUI with Sift's typography and
/// colors — proper headings, bullet / numbered lists, fenced code blocks,
/// blockquotes, tables, and thematic breaks, instead of a collapsed `Text`.
///
/// Keeps the previous call-site API. During streaming a trailing caret glyph is
/// appended so it tracks the last character (static, not blinking — MarkdownUI
/// re-renders the whole document, so an inline blinking caret isn't practical).
struct MarkdownText: View {
    private let content: String

    init(_ text: String, streamingCaret: Bool = false) {
        let normalized = MarkdownNormalizer.normalize(text)
        self.content = streamingCaret ? normalized + " ▌" : normalized
    }

    var body: some View {
        Markdown(content)
            .markdownTheme(.sift)
            .textSelection(.enabled)
            .frame(maxWidth: .infinity, alignment: .leading)
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
