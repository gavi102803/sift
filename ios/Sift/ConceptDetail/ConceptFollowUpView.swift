import SwiftUI

/// Lightweight conversation surface. Turns come from the reconciled initial
/// exchange (persisted at capture) plus remote follow-ups. Loading and failure
/// are explicit, status-driven elements — never disguised as a real answer.
struct ConceptFollowUpView: View {
    var concept: Concept
    var turns: [ConceptHistoryTurnDTO]
    var isSubmitting: Bool
    var isRetryingGeneration: Bool = false
    var onRetryGeneration: () -> Void = {}
    var onAddAssistantToNote: (ConceptHistoryTurnDTO) -> Void = { _ in }
    var onRetryAssistant: (ConceptHistoryTurnDTO) -> Void = { _ in }
    var onEditUserTurn: (ConceptHistoryTurnDTO) -> Void = { _ in }

    private var status: CaptureStatus? {
        CaptureStatus(rawValue: concept.captureStatus)
    }

    private var isGenerating: Bool {
        switch status {
        case .draft, .pendingGeneration, .generating: true
        default: false
        }
    }

    private var hasStreamingAssistantTurn: Bool {
        turns.contains { turn in
            turn.role == "assistant"
                && turn.status == "streaming"
                && !turn.content.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            ForEach(turns) { turn in
                ConceptTurnRow(
                    turn: turn,
                    isStreaming: isStreaming(turn),
                    onAddToNote: onAddAssistantToNote,
                    onRetry: onRetryAssistant,
                    onEditUserTurn: onEditUserTurn
                )
            }

            // Status-driven trailing element. Generation is in progress or has
            // failed: show an explicit loading row / retry card, never a turn.
            if isGenerating && !hasStreamingAssistantTurn {
                GeneratingAnswerRow()
            } else if status == .generationFailed {
                GenerationFailureCard(isRetrying: isRetryingGeneration, onRetry: onRetryGeneration)
            } else if turns.isEmpty {
                emptyPrompt
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
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

    private func isStreaming(_ turn: ConceptHistoryTurnDTO) -> Bool {
        turn.role == "assistant" && turn.status == "streaming"
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

/// Independent failure card with an inline retry — not a fake assistant answer.
/// The original question is preserved (as the user turn above) and the saved
/// draft survives app restarts, so retry never asks the user to retype.
private struct GenerationFailureCard: View {
    var isRetrying: Bool = false
    var onRetry: () -> Void = {}

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: "exclamationmark.triangle")
                .font(.system(size: 16, weight: .regular))
                .foregroundStyle(SiftColor.danger)
                .padding(.top, 1)
            VStack(alignment: .leading, spacing: 6) {
                Text(CompanionCopy.generationTitle)
                    .font(SiftFont.sans(14, .semibold))
                    .foregroundStyle(SiftColor.textPrimary)
                Text(CompanionCopy.generationBody)
                    .font(SiftFont.cardDesc)
                    .foregroundStyle(SiftColor.textMuted)
                    .lineSpacing(2)
                Button(action: onRetry) {
                    HStack(spacing: 6) {
                        if isRetrying {
                            ProgressView().controlSize(.small)
                        } else {
                            Image(systemName: "arrow.clockwise")
                                .font(.system(size: 12, weight: .semibold))
                            Text("Try again")
                                .font(SiftFont.sans(13, .semibold))
                        }
                    }
                    .foregroundStyle(SiftColor.accent)
                }
                .buttonStyle(.plain)
                .disabled(isRetrying)
                .padding(.top, 2)
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
