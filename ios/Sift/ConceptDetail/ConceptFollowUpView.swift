import SwiftUI

/// Lightweight conversation surface. The original capture query (when present)
/// is shown as a temporary fallback bubble; loading and failure are explicit
/// and never disguised as a real assistant answer.
struct ConceptFollowUpView: View {
    var concept: Concept
    var turns: [ConceptHistoryTurnDTO]
    var isSubmitting: Bool
    var lastAnswerSource: AnswerSourceDTO?
    /// Pre-gated by the coordinator: non-nil only when the original query should
    /// be shown (there is fallback text and no matching real user turn yet).
    var captureFallback: String?

    private var status: CaptureStatus? {
        CaptureStatus(rawValue: concept.captureStatus)
    }

    private var isGenerating: Bool {
        switch status {
        case .draft, .pendingGeneration, .generating: true
        default: false
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            if let captureFallback {
                ConceptUserBubble(text: captureFallback, lineLimit: 8)
            }

            if turns.isEmpty {
                emptyStateContent
            } else {
                ForEach(turns) { turn in
                    ConceptTurnRow(
                        turn: turn,
                        isStreaming: isStreaming(turn),
                        showSavedChip: showsSavedChip(turn)
                    )
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    @ViewBuilder
    private var emptyStateContent: some View {
        if isGenerating {
            GeneratingAnswerRow()
        } else if status == .generationFailed {
            GenerationFailureCard()
        } else if captureFallback != nil {
            // Ready, just seeded from capture: surface the first card as the answer.
            AssistantMessage(text: initialAnswerText)
        } else {
            emptyPrompt
        }
    }

    private var emptyPrompt: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Ask a follow-up to grow this concept.")
                .font(SiftFont.body)
                .foregroundStyle(SiftColor.textMuted)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.vertical, 8)
    }

    private var initialAnswerText: String {
        if let blocks = concept.note?.blocks {
            let body = ReadingContent.orderedBlocks(blocks)
                .prefix(2)
                .map(\.content)
                .joined(separator: "\n\n")
            if !body.isEmpty { return body }
        }
        return concept.oneLineExplanation.isEmpty
            ? "Sift created the first concept card. Ask a follow-up to go deeper."
            : concept.oneLineExplanation
    }

    private func isStreaming(_ turn: ConceptHistoryTurnDTO) -> Bool {
        isSubmitting && turn.role == "assistant" && turn.id == turns.last?.id
    }

    private func showsSavedChip(_ turn: ConceptHistoryTurnDTO) -> Bool {
        !isSubmitting
            && turn.role == "assistant"
            && turn.id == turns.last?.id
            && lastAnswerSource != nil
            && !turn.content.isEmpty
    }
}

/// Explicit "Sift is writing the first card" state — clearly a loading state.
private struct GeneratingAnswerRow: View {
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
                Text("Writing the first card…")
                    .font(SiftFont.body)
                    .foregroundStyle(SiftColor.textMuted)
                StreamingCaret()
                    .padding(.leading, 2)
                    .padding(.bottom, 3)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.vertical, 4)
    }
}

/// Independent failure card with a retry path — not a fake assistant answer.
private struct GenerationFailureCard: View {
    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: "exclamationmark.triangle")
                .font(.system(size: 16, weight: .regular))
                .foregroundStyle(SiftColor.danger)
                .padding(.top, 1)
            VStack(alignment: .leading, spacing: 4) {
                Text("Couldn’t generate this card")
                    .font(SiftFont.sans(14, .semibold))
                    .foregroundStyle(SiftColor.textPrimary)
                Text("Return to Capture to retry or archive this saved capture.")
                    .font(SiftFont.cardDesc)
                    .foregroundStyle(SiftColor.textMuted)
                    .lineSpacing(2)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .background(SiftColor.danger.opacity(0.10), in: RoundedRectangle(cornerRadius: SiftRadius.card, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: SiftRadius.card, style: .continuous)
                .strokeBorder(SiftColor.danger.opacity(0.25), lineWidth: 1)
        )
    }
}
