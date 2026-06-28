import SwiftUI

// MARK: - Note block vocabulary (shared by reading + proposal copy)

/// Human title for a note block type. Single source of truth.
func noteBlockTitle(_ blockType: String) -> String {
    switch NoteBlockType(rawValue: blockType) {
    case .whatItIs: "What it is"
    case .whyItMatters: "Why it matters"
    case .example: "Example"
    case .commonMisunderstandings: "Distinction"
    case .relatedConceptsDisplay: "Related concepts"
    case .userTakeaways: "Your takeaways"
    case .none: blockType
    }
}

/// The order content blocks read in the card — by understanding priority,
/// not by storage order. `relatedConceptsDisplay` is handled by the Related
/// section, so it is intentionally absent here.
enum ReadingContent {
    static let order: [NoteBlockType] = [
        .whatItIs,
        .whyItMatters,
        .example,
        .commonMisunderstandings,
        .userTakeaways
    ]

    /// Content blocks in reading order, skipping empties.
    static func orderedBlocks(_ blocks: [NoteBlock]) -> [NoteBlock] {
        order.compactMap { type in
            blocks.first { block in
                block.blockType == type.rawValue
                    && !block.content.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            }
        }
    }
}

// MARK: - Suggested update copy (deterministic + safe)

/// Turns a backend proposal rationale into user-facing copy. The rationale may
/// contain internal language ("replace primary block due to stale base
/// revision"), so it is only shown when clean; otherwise we fall back to a
/// deterministic phrase keyed off the target block.
enum ProposalCopy {
    /// Internal terms that disqualify a rationale from being shown verbatim.
    static let blocklist = [
        "patch", "merge", "revision", "operation", "policy",
        "needs_confirmation", "stale", "basenoterevision"
    ]

    static func isClean(_ rationale: String) -> Bool {
        let lower = rationale.lowercased()
        return !blocklist.contains { lower.contains($0) }
    }

    /// `targetTitle` is the human title of the block the update touches, if known.
    static func userFacingText(rationale: String, targetTitle: String?) -> String {
        let trimmed = rationale.trimmingCharacters(in: .whitespacesAndNewlines)
        if !trimmed.isEmpty, isClean(trimmed) {
            return trimmed
        }
        if let targetTitle, !targetTitle.isEmpty {
            return "Suggested update to “\(targetTitle)”."
        }
        return "Sift found an update worth reviewing."
    }
}

// MARK: - Conversation timeline (authority + offline fallback)

/// Decides what the follow-up timeline shows.
///
/// Authority model:
/// - **Backend conversation history is the durable authority.** The backend now
///   persists the initial user turn *and* the initial assistant turn.
/// - **The local `initialCapture` exchange is an optimistic / offline fallback
///   only** — shown immediately after capture and while the request is
///   in-flight, failed, or offline. Once backend history is read it is
///   superseded.
///
/// The initial exchange is treated as one logical pair: we never per-message
/// text-merge local and remote (which would duplicate when the assistant
/// wording differs slightly). When remote history is present it wins outright;
/// the local pair is only prepended (as a whole) if the remote somehow lacks
/// the original question.
enum ConversationTimeline {
    /// The optimistic initial exchange from locally stored messages: the capture
    /// question and its first answer, tagged `initialCapture`. The `failed`
    /// marker is excluded — a generation failure is surfaced as a retry card,
    /// never as a conversation turn.
    static func initialExchange(from messages: [ConversationMessage]) -> [ConceptHistoryTurnDTO] {
        messages
            .filter { message in
                message.updateMode == LocalConversationMarker.initialCapture
                    && ConversationRole(rawValue: message.role) != nil
            }
            .sorted { $0.createdAt < $1.createdAt }
            .map { message in
                ConceptHistoryTurnDTO(id: message.id, role: message.role, content: message.content)
            }
    }

    /// The most recent failed follow-up *draft*: a user message tagged with the
    /// exact `failed` marker. Identified precisely — never by "unknown update
    /// mode" — so the initial question is never mistaken for a draft.
    static func failedFollowUpDraft(from messages: [ConversationMessage]) -> String? {
        messages
            .filter { message in
                message.role == ConversationRole.user.rawValue
                    && message.updateMode == LocalConversationMarker.failed
            }
            .sorted { $0.createdAt > $1.createdAt }
            .first?
            .content
    }

    /// The display timeline. Remote (backend) history is authoritative; the local
    /// initial exchange is only a fallback until it arrives.
    static func displayTurns(
        localInitial: [ConceptHistoryTurnDTO],
        remote: [ConceptHistoryTurnDTO]
    ) -> [ConceptHistoryTurnDTO] {
        // Remote not arrived yet → show the optimistic local exchange.
        guard !remote.isEmpty else { return localInitial }
        // Remote present and already contains the initial exchange → it is
        // authoritative and the local pair is superseded.
        guard let question = localInitial.first(where: { $0.role == ConversationRole.user.rawValue })?.content,
              !remoteContainsQuestion(remote, question: question) else {
            return remote
        }
        // Defensive: remote lacks the original question → prepend the whole local
        // pair (never split it, never per-message text-merge).
        return localInitial + remote
    }

    /// The assistant content to show once a streamed turn completes. The final
    /// answer is authoritative and covers terminal-only streams — a retry that
    /// returns the completed result with no replayed deltas — so an empty
    /// streamed bubble is never left behind. Streamed text is used only if the
    /// final answer is empty.
    static func resolvedAssistantContent(streamed: String, finalAnswer: String) -> String {
        finalAnswer.isEmpty ? streamed : finalAnswer
    }

    private static func remoteContainsQuestion(_ remote: [ConceptHistoryTurnDTO], question: String) -> Bool {
        let key = normalized(question)
        return remote.contains { turn in
            turn.role == ConversationRole.user.rawValue && normalized(turn.content) == key
        }
    }

    private static func normalized(_ value: String) -> String {
        value.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    }
}

// MARK: - Markdown body

struct MarkdownText: View {
    var text: String

    init(_ text: String) {
        self.text = text
    }

    private var attributedText: AttributedString {
        (try? AttributedString(
            markdown: text,
            options: AttributedString.MarkdownParsingOptions(interpretedSyntax: .full)
        )) ?? AttributedString(text)
    }

    var body: some View {
        Text(attributedText)
            .font(SiftFont.body)
            .lineSpacing(5)
            .textSelection(.enabled)
    }
}

// MARK: - Conversation rows

/// A user message bubble (also used for the temporary capture fallback bubble).
struct ConceptUserBubble: View {
    var text: String
    var lineLimit: Int? = nil

    var body: some View {
        HStack {
            Spacer(minLength: 44)
            MarkdownText(text)
                .lineLimit(lineLimit)
                .foregroundStyle(SiftColor.textPrimary)
                .padding(.horizontal, 14)
                .padding(.vertical, 11)
                .background(
                    SiftColor.surfaceSoftHi,
                    in: UnevenRoundedRectangle(
                        topLeadingRadius: 16, bottomLeadingRadius: 16,
                        bottomTrailingRadius: 6, topTrailingRadius: 16,
                        style: .continuous
                    )
                )
        }
    }
}

struct ConceptTurnRow: View {
    var turn: ConceptHistoryTurnDTO
    var isStreaming: Bool = false
    var showSavedChip: Bool = false

    var body: some View {
        if turn.role == "assistant" {
            AssistantMessage(
                text: turn.content,
                isStreaming: isStreaming,
                showSavedChip: showSavedChip,
                source: turn.answerSource
            )
        } else {
            ConceptUserBubble(text: turn.content)
        }
    }
}

struct AssistantMessage: View {
    var text: String
    var isStreaming: Bool = false
    var showSavedChip: Bool = false
    var source: AnswerSourceDTO? = nil

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
                MarkdownText(text)
                    .foregroundStyle(SiftColor.textSecondary)
                if isStreaming {
                    StreamingCaret()
                        .padding(.leading, 2)
                        .padding(.bottom, 3)
                }
            }

            if let source, source.citations?.isEmpty == false {
                SiftSourceLink(source: source)
            }

            if showSavedChip {
                HStack(spacing: 6) {
                    Image(systemName: "checkmark")
                        .font(.system(size: 10, weight: .bold))
                    Text("Saved to note")
                        .font(SiftFont.sans(12, .medium))
                }
                .foregroundStyle(SiftColor.accentTextOnWash)
                .padding(.horizontal, 10)
                .padding(.vertical, 5)
                .background(SiftColor.accentWash, in: Capsule())
                .overlay(Capsule().strokeBorder(SiftColor.accentBorder, lineWidth: 1))
                .padding(.top, 2)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.vertical, 4)
    }
}

/// Blinking accent caret trailing streaming text.
struct StreamingCaret: View {
    @State private var visible = true

    var body: some View {
        RoundedRectangle(cornerRadius: 2, style: .continuous)
            .fill(SiftColor.accent)
            .frame(width: 8, height: 17)
            .opacity(visible ? 1 : 0)
            .task {
                while !Task.isCancelled {
                    visible.toggle()
                    try? await Task.sleep(for: .milliseconds(500))
                }
            }
    }
}

/// Quiet "View sources" disclosure — the content-basis entry, not a confidence
/// module. Only meaningful when citations exist.
struct SiftSourceLink: View {
    var source: AnswerSourceDTO
    @State private var expanded = false

    private var citations: [CitationDTO] { source.citations ?? [] }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Button {
                withAnimation(.easeInOut(duration: 0.18)) { expanded.toggle() }
            } label: {
                HStack(spacing: 6) {
                    Image(systemName: "text.quote")
                        .font(.system(size: 11, weight: .medium))
                    Text(expanded ? "Hide sources" : "View sources")
                        .font(SiftFont.sans(12, .medium))
                    Image(systemName: "chevron.down")
                        .font(.system(size: 9, weight: .bold))
                        .rotationEffect(.degrees(expanded ? 0 : -90))
                }
                .foregroundStyle(SiftColor.textMuted)
            }
            .buttonStyle(.plain)

            if expanded {
                ForEach(citations) { citation in
                    if let url = URL(string: citation.url) {
                        Link(destination: url) {
                            HStack(spacing: 6) {
                                Image(systemName: "arrow.up.right")
                                    .font(.system(size: 10, weight: .semibold))
                                Text(citation.title)
                                    .font(SiftFont.sans(12))
                                    .lineLimit(2)
                                    .multilineTextAlignment(.leading)
                            }
                            .foregroundStyle(SiftColor.accentTextOnWash)
                        }
                    }
                }
            }
        }
    }
}

// MARK: - Compact concept anchor (follow-up top inset)

struct ConceptAnchorBar: View {
    var concept: Concept
    var hasPendingProposal: Bool
    var onTap: () -> Void

    var body: some View {
        Button(action: onTap) {
            HStack(spacing: 12) {
                VStack(alignment: .leading, spacing: 3) {
                    Text(concept.displayTitle)
                        .font(SiftFont.sans(15, .semibold))
                        .foregroundStyle(SiftColor.textPrimary)
                        .lineLimit(1)
                    if hasPendingProposal {
                        Text("An update is ready to review")
                            .font(SiftFont.sans(12))
                            .foregroundStyle(SiftColor.accentTextOnWash)
                            .lineLimit(1)
                    } else {
                        Text(concept.oneLineExplanation.isEmpty
                             ? "Back to card"
                             : concept.oneLineExplanation)
                            .font(SiftFont.sans(12))
                            .foregroundStyle(SiftColor.textFaint)
                            .lineLimit(1)
                    }
                }
                Spacer(minLength: 8)
                Image(systemName: "chevron.up")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(SiftColor.textFaint)
            }
            .padding(.vertical, 10)
            .padding(.horizontal, 14)
            // Frosted-glass component over the unified background — no opaque
            // gray card.
            .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: SiftRadius.card, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: SiftRadius.card, style: .continuous)
                    .strokeBorder(hasPendingProposal ? SiftColor.accentBorder : Color.white.opacity(0.08), lineWidth: 1)
            )
        }
        .buttonStyle(.plain)
        .accessibilityLabel("Show concept card")
    }
}

// MARK: - Editors

struct ConceptSummaryEditor: View {
    @Binding var title: String
    @Binding var explanation: String
    @Binding var tags: String
    @Binding var topics: String
    var onCancel: () -> Void
    var onSave: () -> Void

    var body: some View {
        Form {
            Section("Concept") {
                TextField("Title", text: $title)
                TextField("One-line explanation", text: $explanation, axis: .vertical)
                    .lineLimit(2...5)
            }
            Section("Organization") {
                TextField("Topics", text: $topics, axis: .vertical)
                    .lineLimit(1...3)
                TextField("Tags", text: $tags, axis: .vertical)
                    .lineLimit(1...3)
            }
        }
        .navigationTitle("Edit Concept")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .cancellationAction) {
                Button("Cancel", action: onCancel)
            }
            ToolbarItem(placement: .confirmationAction) {
                Button("Save", action: onSave)
                    .disabled(title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }
    }
}

struct NoteBlockEditor: View {
    var title: String
    @Binding var content: String
    var onCancel: () -> Void
    var onSave: () -> Void

    var body: some View {
        Form {
            Section(title) {
                TextEditor(text: $content)
                    .frame(minHeight: 180)
            }
        }
        .navigationTitle("Edit \(title)")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .cancellationAction) {
                Button("Cancel", action: onCancel)
            }
            ToolbarItem(placement: .confirmationAction) {
                Button("Save", action: onSave)
                    .disabled(content.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }
    }
}

enum SiftStreamingError: LocalizedError {
    case incomplete

    var errorDescription: String? {
        "The streamed response ended before Sift received the final answer."
    }
}
