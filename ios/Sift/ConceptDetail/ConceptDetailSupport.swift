import SwiftUI
#if canImport(UIKit)
import UIKit
#endif

// MARK: - Note block vocabulary (shared by reading + proposal copy)

/// Human title for a note block type. Single source of truth.
func noteBlockTitle(_ blockType: String) -> String {
    switch NoteBlockType(rawValue: blockType) {
    case .oneLineDefinition: "Definition"
    case .whatItIs: "What it is"
    case .whyItMatters: "Why it matters"
    case .example: "Example"
    case .distinction: "Distinction"
    case .misconception: "Misconception"
    case .userContext: "User context"
    case .openQuestion: "Open question"
    case .relatedConcepts: "Related concepts"
    case .caveat: "Caveat"
    case .commonMisunderstandings: "Distinction"
    case .relatedConceptsDisplay: "Related concepts"
    case .userTakeaways: "Your takeaways"
    case .none: formattedBlockType(blockType)
    }
}

private func formattedBlockType(_ blockType: String) -> String {
    let spaced = blockType.reduce(into: "") { partial, character in
        if character.isUppercase, !partial.isEmpty {
            partial.append(" ")
        }
        partial.append(character)
    }
    let trimmed = spaced.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !trimmed.isEmpty else { return "Note" }
    return trimmed.prefix(1).uppercased() + trimmed.dropFirst()
}

/// Content blocks in backend/user order. Unknown block types are still shown:
/// storage truth beats a narrow display whitelist.
enum ReadingContent {
    static func orderedBlocks(_ blocks: [NoteBlock]) -> [NoteBlock] {
        blocks.enumerated()
            .filter { _, block in
                block.blockType != NoteBlockType.relatedConceptsDisplay.rawValue
                    && !block.content.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            }
            .sorted { lhs, rhs in
                let lhsPosition = lhs.element.position ?? lhs.offset
                let rhsPosition = rhs.element.position ?? rhs.offset
                if lhsPosition == rhsPosition {
                    return lhs.offset < rhs.offset
                }
                return lhsPosition < rhsPosition
            }
            .map(\.element)
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
                ConceptHistoryTurnDTO(
                    id: message.id,
                    role: message.role,
                    content: message.content,
                    status: message.operationStatus ?? "completed"
                )
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

/// Renders markdown as stacked block elements (headings, bullet / numbered
/// lists, spaced paragraphs) with inline bold/italic/code — instead of one
/// collapsed `Text`, which is what made replies read as a single wall. When
/// `streamingCaret` is set, a blinking accent caret is appended *inline* after
/// the last block's last character (so it tracks the text, not the right edge).
struct MarkdownText: View {
    private let blocks: [MarkdownBlock]
    var streamingCaret: Bool = false

    init(_ text: String, streamingCaret: Bool = false) {
        self.blocks = MarkdownBlock.parse(MarkdownNormalizer.normalize(text))
        self.streamingCaret = streamingCaret
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            ForEach(Array(blocks.enumerated()), id: \.offset) { index, block in
                blockView(block, isLast: index == blocks.count - 1)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .textSelection(.enabled)
    }

    @ViewBuilder
    private func blockView(_ block: MarkdownBlock, isLast: Bool) -> some View {
        let caret = streamingCaret && isLast
        switch block.kind {
        case .heading(let level):
            line(styled(block.text, font: headingFont(level), color: SiftColor.textPrimary), caret: caret)
                .padding(.top, 2)
        case .paragraph:
            line(styled(block.text, font: SiftFont.body, color: SiftColor.textSecondary), caret: caret)
        case .bullet:
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text("•").font(SiftFont.body).foregroundStyle(SiftColor.textFaint)
                line(styled(block.text, font: SiftFont.body, color: SiftColor.textSecondary), caret: caret)
            }
        case .numbered(let n):
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text("\(n).").font(SiftFont.body).monospacedDigit().foregroundStyle(SiftColor.textFaint)
                line(styled(block.text, font: SiftFont.body, color: SiftColor.textSecondary), caret: caret)
            }
        case .quote:
            HStack(spacing: 10) {
                RoundedRectangle(cornerRadius: 1.5, style: .continuous)
                    .fill(SiftColor.hairline)
                    .frame(width: 3)
                line(styled(block.text, font: SiftFont.body, color: SiftColor.textMuted), caret: caret)
            }
            .fixedSize(horizontal: false, vertical: true)
        case .rule:
            Rectangle()
                .fill(SiftColor.hairline)
                .frame(height: 1)
                .padding(.vertical, 2)
        }
    }

    private func styled(_ text: String, font: Font, color: Color) -> Text {
        Text(MarkdownInline.attributed(text)).font(font).foregroundColor(color)
    }

    private func headingFont(_ level: Int) -> Font {
        switch level {
        case 1: return SiftFont.sans(19, .bold)
        case 2: return SiftFont.sans(17, .semibold)
        default: return SiftFont.sans(15, .semibold)
        }
    }

    @ViewBuilder
    private func line(_ base: Text, caret: Bool) -> some View {
        Group {
            if caret {
                TimelineView(.periodic(from: .now, by: 0.5)) { context in
                    let on = Int(context.date.timeIntervalSince1970 * 2) % 2 == 0
                    base + Text("▌").foregroundColor(on ? SiftColor.accent : .clear)
                }
            } else {
                base
            }
        }
        .lineSpacing(5)
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// One parsed markdown block. Inline emphasis is resolved at render time.
struct MarkdownBlock {
    enum Kind: Equatable { case heading(Int), paragraph, bullet, numbered(Int), quote, rule }
    var kind: Kind
    var text: String

    static func parse(_ raw: String) -> [MarkdownBlock] {
        var blocks: [MarkdownBlock] = []
        var paragraph: [String] = []
        // Index of the list item that following unmarked lines continue (the
        // model wraps a bullet's body onto an indented next line, no blank gap).
        var continuation: Int?

        func flushParagraph() {
            let joined = paragraph.joined(separator: " ").trimmingCharacters(in: .whitespaces)
            paragraph.removeAll()
            if !joined.isEmpty { blocks.append(MarkdownBlock(kind: .paragraph, text: joined)) }
        }

        for rawLine in raw.components(separatedBy: "\n") {
            let lineText = rawLine.trimmingCharacters(in: .whitespaces)
            if lineText.isEmpty {
                flushParagraph(); continuation = nil; continue
            }
            if isRule(lineText) {
                flushParagraph(); continuation = nil
                blocks.append(MarkdownBlock(kind: .rule, text: ""))
            } else if let heading = headingLevel(lineText) {
                flushParagraph(); continuation = nil
                blocks.append(MarkdownBlock(kind: .heading(heading.level), text: heading.text))
            } else if let quote = quoteText(lineText) {
                flushParagraph(); continuation = nil
                blocks.append(MarkdownBlock(kind: .quote, text: quote))
            } else if let bullet = bulletText(lineText) {
                flushParagraph()
                blocks.append(MarkdownBlock(kind: .bullet, text: bullet))
                continuation = blocks.count - 1
            } else if let numbered = numberedItem(lineText) {
                flushParagraph()
                blocks.append(MarkdownBlock(kind: .numbered(numbered.index), text: numbered.text))
                continuation = blocks.count - 1
            } else if let target = continuation, paragraph.isEmpty {
                // Continuation line for the preceding list item.
                blocks[target].text += " " + lineText
            } else {
                paragraph.append(lineText)
            }
        }
        flushParagraph()

        if blocks.isEmpty {
            return [MarkdownBlock(kind: .paragraph, text: raw.trimmingCharacters(in: .whitespacesAndNewlines))]
        }
        return blocks
    }

    private static func isRule(_ line: String) -> Bool {
        guard line.count >= 3 else { return false }
        return Set(line) == ["-"] || Set(line) == ["*"] || Set(line) == ["_"]
    }

    private static func quoteText(_ line: String) -> String? {
        guard line.hasPrefix(">") else { return nil }
        return String(line.dropFirst()).trimmingCharacters(in: .whitespaces)
    }

    private static func headingLevel(_ line: String) -> (level: Int, text: String)? {
        guard line.hasPrefix("#") else { return nil }
        let hashes = line.prefix { $0 == "#" }.count
        guard hashes <= 6, line.dropFirst(hashes).hasPrefix(" ") else { return nil }
        return (min(hashes, 3), String(line.dropFirst(hashes)).trimmingCharacters(in: .whitespaces))
    }

    private static func bulletText(_ line: String) -> String? {
        for marker in ["- ", "* ", "• ", "· "] where line.hasPrefix(marker) {
            return String(line.dropFirst(marker.count)).trimmingCharacters(in: .whitespaces)
        }
        return nil
    }

    private static func numberedItem(_ line: String) -> (index: Int, text: String)? {
        let digits = line.prefix { $0.isNumber }
        guard !digits.isEmpty, let index = Int(digits) else { return nil }
        let rest = line.dropFirst(digits.count)
        guard let sep = rest.first, sep == "." || sep == ")", rest.dropFirst().hasPrefix(" ") else { return nil }
        return (index, String(rest.dropFirst()).trimmingCharacters(in: .whitespaces))
    }
}

enum MarkdownInline {
    /// Inline-only parse: resolves **bold**, *italic*, `code` while preserving
    /// the surrounding text and whitespace (no block collapsing).
    static func attributed(_ text: String) -> AttributedString {
        (try? AttributedString(
            markdown: text,
            options: AttributedString.MarkdownParsingOptions(interpretedSyntax: .inlineOnlyPreservingWhitespace)
        )) ?? AttributedString(text)
    }
}

enum MarkdownNormalizer {
    private static let headings = [
        "What it is",
        "Why it matters",
        "Example",
        "Your takeaways",
        "Common misunderstandings",
        "Distinction"
    ]

    static func normalize(_ text: String) -> String {
        var normalized = text.trimmingCharacters(in: .whitespacesAndNewlines)
        for heading in headings {
            normalized = normalized.replacingOccurrences(
                of: "**\(heading)**",
                with: "\n\n**\(heading)**\n\n"
            )
            normalized = normalized.replacingOccurrences(
                of: "\(heading)",
                with: "\n\n**\(heading)**\n\n"
            )
            normalized = normalized.replacingOccurrences(of: "**\n\n**", with: "")
            normalized = normalized.replacingOccurrences(of: "\n\n\n\n", with: "\n\n")
        }
        while normalized.contains("\n\n\n") {
            normalized = normalized.replacingOccurrences(of: "\n\n\n", with: "\n\n")
        }
        return normalized.trimmingCharacters(in: .whitespacesAndNewlines)
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
    var onAddToNote: (ConceptHistoryTurnDTO) -> Void = { _ in }
    var onRetry: (ConceptHistoryTurnDTO) -> Void = { _ in }
    var onEditUserTurn: (ConceptHistoryTurnDTO) -> Void = { _ in }

    var body: some View {
        if turn.role == "assistant" {
            AssistantMessage(
                turn: turn,
                text: turn.content,
                isStreaming: isStreaming,
                source: turn.answerSource,
                onAddToNote: { onAddToNote(turn) },
                onRetry: { onRetry(turn) }
            )
        } else {
            VStack(alignment: .trailing, spacing: 6) {
                ConceptUserBubble(text: turn.content)
                MessageActionBar(
                    actions: [
                        MessageAction(icon: "doc.on.doc", title: "Copy") {
                            copyToPasteboard(turn.content)
                        },
                        MessageAction(icon: "pencil", title: "Edit") {
                            onEditUserTurn(turn)
                        }
                    ]
                )
            }
        }
    }
}

struct AssistantMessage: View {
    var turn: ConceptHistoryTurnDTO
    var text: String
    var isStreaming: Bool = false
    var source: AnswerSourceDTO? = nil
    var onAddToNote: () -> Void = {}
    var onRetry: () -> Void = {}

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 7) {
                SiftSymbol(size: 18)
                    .frame(width: 18, height: 18)
                Text("Sift")
                    .font(SiftFont.sans(13, .semibold))
                    .foregroundStyle(SiftColor.textPrimary)
            }

            MarkdownText(text, streamingCaret: isStreaming)

            if let source, source.citations?.isEmpty == false {
                SiftSourceLink(source: source)
            }

            if !isStreaming && !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                MessageActionBar(
                    actions: [
                        MessageAction(icon: "plus.square.on.square", title: "Add to note", action: onAddToNote),
                        MessageAction(icon: "doc.on.doc", title: "Copy") {
                            copyToPasteboard(text)
                        },
                        MessageAction(icon: "arrow.clockwise", title: "Retry", action: onRetry)
                    ]
                )
                .padding(.top, 2)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.vertical, 4)
    }
}

enum SourceTokenFormatter {
    static func hideInternalSourceIds(_ text: String) -> String {
        text.replacingOccurrences(
            of: #"src_\d{3}"#,
            with: "来源",
            options: .regularExpression
        )
    }
}

struct MessageAction: Identifiable {
    let id = UUID()
    var icon: String
    var title: String
    var action: () -> Void
}

struct MessageActionBar: View {
    var actions: [MessageAction]

    var body: some View {
        HStack(spacing: 12) {
            ForEach(actions) { action in
                Button(action: action.action) {
                    Image(systemName: action.icon)
                        .font(.system(size: 15, weight: .medium))
                        .foregroundStyle(SiftColor.textMuted)
                        .frame(width: 28, height: 28)
                }
                .buttonStyle(.plain)
                .accessibilityLabel(action.title)
            }
        }
    }
}

private func copyToPasteboard(_ text: String) {
    #if canImport(UIKit)
    UIPasteboard.general.string = text
    #endif
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
                HStack(spacing: 7) {
                    Image(systemName: "globe")
                        .font(.system(size: 12, weight: .semibold))
                    Text("\(citations.count) source\(citations.count == 1 ? "" : "s")")
                        .font(SiftFont.sans(12, .semibold))
                    Image(systemName: "chevron.down")
                        .font(.system(size: 9, weight: .bold))
                        .rotationEffect(.degrees(expanded ? 180 : 0))
                }
                .foregroundStyle(SiftColor.accentTextOnWash)
                .padding(.horizontal, 10)
                .padding(.vertical, 6)
                .background(SiftColor.accentWash, in: Capsule())
            }
            .buttonStyle(.plain)

            if expanded {
                VStack(alignment: .leading, spacing: 8) {
                    ForEach(citations) { citation in
                        SourceCitationCard(citation: citation)
                    }
                }
                .padding(10)
                .background(SiftColor.surfaceSoft, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                .overlay {
                    RoundedRectangle(cornerRadius: 14, style: .continuous)
                        .strokeBorder(SiftColor.hairline, lineWidth: 1)
                }
            }
        }
    }
}

private struct SourceCitationCard: View {
    var citation: CitationDTO

    private var url: URL? { URL(string: citation.url) }
    private var host: String {
        url?.host(percentEncoded: false) ?? citation.url
    }

    var body: some View {
        Group {
            if let url {
                Link(destination: url) {
                    content
                }
            } else {
                content
            }
        }
        .buttonStyle(.plain)
    }

    private var content: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: "arrow.up.right")
                .font(.system(size: 11, weight: .bold))
                .foregroundStyle(SiftColor.accent)
                .frame(width: 22, height: 22)
                .background(SiftColor.accentWash, in: RoundedRectangle(cornerRadius: 7, style: .continuous))

            VStack(alignment: .leading, spacing: 3) {
                Text(citation.title)
                    .font(SiftFont.sans(13, .semibold))
                    .foregroundStyle(SiftColor.textPrimary)
                    .lineLimit(2)
                    .multilineTextAlignment(.leading)
                Text(host)
                    .font(SiftFont.sans(11, .regular))
                    .foregroundStyle(SiftColor.textMuted)
                    .lineLimit(1)
                if let sourceId = citation.sourceId, !sourceId.isEmpty {
                    Text(sourceId)
                        .font(SiftFont.sans(10, .medium))
                        .foregroundStyle(SiftColor.textMuted)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(9)
        .background(SiftColor.surface, in: RoundedRectangle(cornerRadius: 11, style: .continuous))
    }
}

// MARK: - Editors

struct EditableNoteBlock: Identifiable, Equatable {
    let localId: UUID
    var serverId: UUID?
    var blockType: String
    var content: String
    var position: Int?

    var id: UUID { localId }

    init(
        localId: UUID = UUID(),
        serverId: UUID? = nil,
        blockType: String = NoteBlockType.userTakeaways.rawValue,
        content: String = "",
        position: Int? = nil
    ) {
        self.localId = localId
        self.serverId = serverId
        self.blockType = blockType
        self.content = content
        self.position = position
    }

    init(block: NoteBlock, fallbackPosition: Int) {
        self.init(
            serverId: block.id,
            blockType: block.blockType,
            content: block.content,
            position: block.position ?? fallbackPosition
        )
    }

    var request: UpdateConceptNoteBlockRequest {
        UpdateConceptNoteBlockRequest(
            id: serverId,
            blockType: blockType,
            content: content
        )
    }
}

struct ConceptFullNoteEditor: View {
    @Binding var title: String
    @Binding var explanation: String
    @Binding var tags: String
    @Binding var topics: String
    @Binding var blocks: [EditableNoteBlock]
    var errorMessage: String?
    var onCancel: () -> Void
    var onSave: () -> Void

    private var blockTypes: [String] {
        NoteBlockType.allCases
            .filter { $0 != .relatedConceptsDisplay }
            .map(\.rawValue)
    }

    var body: some View {
        Form {
            if let errorMessage {
                Section {
                    Text(errorMessage)
                        .font(SiftFont.cardDesc)
                        .foregroundStyle(SiftColor.danger)
                }
            }

            Section("Concept") {
                TextField("Title", text: $title)
                TextField("One-line explanation", text: $explanation, axis: .vertical)
                    .lineLimit(2...5)
            }

            Section("Note") {
                ForEach($blocks) { $block in
                    VStack(alignment: .leading, spacing: 10) {
                        Picker("Section", selection: $block.blockType) {
                            ForEach(blockTypes, id: \.self) { type in
                                Text(noteBlockTitle(type)).tag(type)
                            }
                        }
                        .pickerStyle(.menu)

                        TextEditor(text: $block.content)
                            .frame(minHeight: 120)
                            .font(SiftFont.body)

                        Button(role: .destructive) {
                            blocks.removeAll { $0.id == block.id }
                            normalizePositions()
                        } label: {
                            Label("Remove section", systemImage: "trash")
                        }
                        .buttonStyle(.borderless)
                    }
                    .padding(.vertical, 6)
                }
                .onMove { source, destination in
                    blocks.move(fromOffsets: source, toOffset: destination)
                    normalizePositions()
                }

                Button {
                    blocks.append(
                        EditableNoteBlock(
                            blockType: NoteBlockType.userTakeaways.rawValue,
                            position: blocks.count
                        )
                    )
                } label: {
                    Label("Add section", systemImage: "plus")
                }
            }

            Section("Organization") {
                TextField("Topics", text: $topics, axis: .vertical)
                    .lineLimit(1...3)
                TextField("Tags", text: $tags, axis: .vertical)
                    .lineLimit(1...3)
            }
        }
        .navigationTitle("Edit Note")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .cancellationAction) {
                Button("Cancel", action: onCancel)
            }
            ToolbarItem(placement: .secondaryAction) {
                EditButton()
            }
            ToolbarItem(placement: .confirmationAction) {
                Button("Save", action: onSave)
                    .disabled(!canSave)
            }
        }
    }

    private var canSave: Bool {
        !title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && blocks.contains { !$0.content.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
    }

    private func normalizePositions() {
        for index in blocks.indices {
            blocks[index].position = index
        }
    }
}

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
