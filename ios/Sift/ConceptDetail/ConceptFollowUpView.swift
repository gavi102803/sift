import SwiftUI

/// Lightweight conversation surface. Turns come from the reconciled initial
/// exchange (persisted at capture) plus remote follow-ups. Loading and failure
/// are explicit, status-driven elements — never disguised as a real answer.
struct ConceptFollowUpView: View {
    var concept: Concept
    var turns: [ConceptHistoryTurnDTO]
    var hiddenTurnId: UUID? = nil
    var isSubmitting: Bool
    var progressLabel: String? = nil
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
        case .draft, .pendingGeneration, .generating, .buildingCard: true
        default: false
        }
    }

    private var hasStreamingAssistantTurn: Bool {
        guard status != .buildingCard else { return false }
        return turns.contains { turn in
            turn.role == "assistant"
                && turn.status == "streaming"
        }
    }

    private var hasCompletedAssistantTurn: Bool {
        turns.contains { turn in
            turn.role == "assistant"
                && turn.status != "streaming"
                && !turn.content.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        }
    }

    private var activeProgressLabel: String? {
        if isSubmitting {
            guard !hasStreamingAssistantTurn || turns.last?.content.isEmpty == true else {
                return nil
            }
            return AgentProgressPresentation.label(
                for: progressLabel,
                isBuildingCard: false
            )
        }
        guard isRetryingGeneration || (isGenerating && !hasStreamingAssistantTurn) else {
            return nil
        }
        return AgentProgressPresentation.label(
            for: progressLabel,
            isBuildingCard: status == .buildingCard || hasCompletedAssistantTurn
        )
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
                .opacity(turn.id == hiddenTurnId ? 0 : 1)
                .accessibilityHidden(turn.id == hiddenTurnId)
            }

            if let activeProgressLabel {
                AgentProgressText(activeProgressLabel)
            }

            // Status-driven trailing element. Generation is in progress or has
            // failed: show an explicit loading row / retry card, never a turn.
            if status == .generationFailed && !isRetryingGeneration {
                GenerationFailureCard(isRetrying: isRetryingGeneration, onRetry: onRetryGeneration)
            } else if turns.isEmpty && activeProgressLabel == nil {
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
        status != .buildingCard
            && turn.role == "assistant"
            && turn.status == "streaming"
    }

}

enum AgentProgressPresentation {
    static func label(for rawLabel: String?, isBuildingCard: Bool) -> String {
        let rawLabel = rawLabel?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        let normalized = rawLabel.lowercased()
        if normalized.contains("card")
            || normalized.contains("saving")
            || normalized.contains("structure") {
            return "Building card…"
        }
        if normalized.contains("search")
            || normalized.contains("research")
            || normalized.contains("retrieval") {
            return "Searching…"
        }
        if normalized.contains("answer")
            || normalized.contains("writing")
            || normalized.contains("think") {
            return "Thinking…"
        }
        if normalized.contains("prepar") {
            return "Preparing…"
        }
        if !rawLabel.isEmpty {
            return rawLabel.hasSuffix("…") || rawLabel.hasSuffix("...")
                ? rawLabel
                : rawLabel + "…"
        }
        return isBuildingCard ? "Building card…" : "Searching…"
    }
}

/// A stable turn-level status inspired by DeepSeek Harness: muted Sift blue is
/// always readable while a brighter blue band crosses the text every 1.8s.
/// Reduce Motion keeps the same label without animation.
struct AgentProgressText: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var shimmerPhase: CGFloat = -1

    var label: String

    init(_ label: String) {
        self.label = label
    }

    var body: some View {
        Text(label)
            .font(SiftFont.sans(13, .semibold))
            .foregroundStyle(SiftColor.accent.opacity(reduceMotion ? 0.8 : 0.42))
            .overlay {
                if !reduceMotion {
                    GeometryReader { geometry in
                        let bandWidth = max(48, geometry.size.width * 0.55)
                        LinearGradient(
                            colors: [
                                SiftColor.accent.opacity(0),
                                SiftColor.accent,
                                SiftColor.accent.opacity(0),
                            ],
                            startPoint: .leading,
                            endPoint: .trailing
                        )
                        .frame(width: bandWidth)
                        .offset(
                            x: ((shimmerPhase + 1) / 2)
                                * (geometry.size.width + bandWidth) - bandWidth
                        )
                    }
                    .mask {
                        Text(label)
                            .font(SiftFont.sans(13, .semibold))
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
            }
            .fixedSize(horizontal: true, vertical: false)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.vertical, 4)
            .accessibilityLabel("Agent progress: \(label)")
            .accessibilityIdentifier("agent.progress")
            .onAppear(perform: startShimmer)
            .onChange(of: reduceMotion) { _, _ in startShimmer() }
    }

    private func startShimmer() {
        shimmerPhase = -1
        guard !reduceMotion else { return }
        withAnimation(.linear(duration: 1.8).repeatForever(autoreverses: false)) {
            shimmerPhase = 1
        }
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
