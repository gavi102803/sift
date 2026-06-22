import SwiftData
import SwiftUI

struct ConceptDetailView: View {
    @Environment(\.appServices) private var appServices
    @Environment(\.modelContext) private var modelContext
    @Query private var concepts: [Concept]
    @State private var followUpText = ""
    @State private var lastAnswer: String?
    @State private var errorMessage: String?
    @State private var isSubmittingFollowUp = false

    private var conceptId: UUID

    init(conceptId: UUID) {
        self.conceptId = conceptId
        _concepts = Query(filter: #Predicate<Concept> { concept in
            concept.id == conceptId
        })
    }

    private var concept: Concept? {
        concepts.first
    }

    var body: some View {
        Group {
            if let concept {
                ScrollView {
                    VStack(alignment: .leading, spacing: 20) {
                        header(for: concept)
                        if let lastAnswer {
                            answerSection(lastAnswer)
                        }
                        if let errorMessage {
                            Text(errorMessage)
                                .font(.footnote)
                                .foregroundStyle(.red)
                        }
                        noteSection(for: concept)
                    }
                    .padding(20)
                }
                .safeAreaInset(edge: .bottom) {
                    followUpComposer
                }
            } else {
                ContentUnavailableView(
                    "Concept not found",
                    systemImage: "exclamationmark.magnifyingglass",
                    description: Text("This card may have been deleted.")
                )
            }
        }
        .navigationTitle(concept?.displayTitle ?? "Concept")
        .navigationBarTitleDisplayMode(.inline)
    }

    private func header(for concept: Concept) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(concept.displayTitle)
                .font(.largeTitle.weight(.semibold))
            HStack {
                Label(concept.maturity, systemImage: "leaf")
                Label(concept.captureStatus, systemImage: "tray")
            }
            .font(.caption)
            .foregroundStyle(.secondary)

            if !concept.oneLineExplanation.isEmpty {
                Text(concept.oneLineExplanation)
                    .font(.body)
            }
        }
    }

    private func noteSection(for concept: Concept) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Note")
                .font(.headline)

            if let blocks = concept.note?.blocks, !blocks.isEmpty {
                ForEach(blocks) { block in
                    NoteBlockView(block: block)
                }
            } else {
                ContentUnavailableView(
                    "No note yet",
                    systemImage: "doc.text",
                    description: Text("Generate or edit this concept to start the card.")
                )
            }
        }
    }

    private func answerSection(_ answer: String) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Answer")
                .font(.headline)
            Text(answer)
                .font(.body)
                .foregroundStyle(.primary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(.background, in: RoundedRectangle(cornerRadius: 8))
        .overlay {
            RoundedRectangle(cornerRadius: 8)
                .stroke(.quaternary, lineWidth: 1)
        }
    }

    private var followUpComposer: some View {
        HStack(spacing: 10) {
            TextField("Ask a follow-up", text: $followUpText, axis: .vertical)
                .textFieldStyle(.plain)
                .lineLimit(1...4)
                .padding(10)
                .background(.background, in: RoundedRectangle(cornerRadius: 8))
                .overlay {
                    RoundedRectangle(cornerRadius: 8)
                        .stroke(.quaternary, lineWidth: 1)
                }

            Button {
                if let concept {
                    Task {
                        await submitFollowUp(for: concept)
                    }
                }
            } label: {
                if isSubmittingFollowUp {
                    ProgressView()
                        .frame(width: 34, height: 34)
                } else {
                    Image(systemName: "arrow.up")
                        .frame(width: 34, height: 34)
                }
            }
            .buttonStyle(.borderedProminent)
            .disabled(
                isSubmittingFollowUp
                    || followUpText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            )
            .accessibilityLabel("Submit follow-up")
        }
        .padding(12)
        .background(.bar)
    }

    private func submitFollowUp(for concept: Concept) async {
        let question = followUpText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !question.isEmpty else { return }

        isSubmittingFollowUp = true
        errorMessage = nil
        do {
            let response = try await appServices.apiClient.submitTurn(
                conceptId: concept.id,
                request: ConceptTurnRequest(question: question)
            )
            _ = try ConceptLocalStore(modelContext: modelContext).upsertConcept(from: response.concept)
            lastAnswer = response.answer
            followUpText = ""
        } catch {
            errorMessage = error.localizedDescription
        }
        isSubmittingFollowUp = false
    }
}

private struct NoteBlockView: View {
    var block: NoteBlock

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(title(for: block.blockType))
                    .font(.subheadline.weight(.semibold))
                if block.isUserLocked {
                    Image(systemName: "lock")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }

            Text(block.content)
                .font(.body)
                .foregroundStyle(.primary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(.background, in: RoundedRectangle(cornerRadius: 8))
        .overlay {
            RoundedRectangle(cornerRadius: 8)
                .stroke(.quaternary, lineWidth: 1)
        }
    }

    private func title(for blockType: String) -> String {
        switch NoteBlockType(rawValue: blockType) {
        case .whatItIs:
            "What It Is"
        case .whyItMatters:
            "Why It Matters"
        case .example:
            "Example"
        case .commonMisunderstandings:
            "Common Misunderstandings"
        case .relatedConceptsDisplay:
            "Related Concepts"
        case .userTakeaways:
            "Takeaways"
        case .none:
            blockType
        }
    }
}
