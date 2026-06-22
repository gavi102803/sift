import SwiftData
import SwiftUI

struct ConceptDetailView: View {
    @Environment(\.appServices) private var appServices
    @Environment(\.modelContext) private var modelContext
    @Query private var concepts: [Concept]
    @Query private var proposals: [ConceptUpdateProposal]
    @State private var followUpText = ""
    @State private var lastAnswer: String?
    @State private var errorMessage: String?
    @State private var isSubmittingFollowUp = false
    @State private var resolvingProposalId: UUID?

    private var conceptId: UUID

    init(conceptId: UUID) {
        self.conceptId = conceptId
        _concepts = Query(filter: #Predicate<Concept> { concept in
            concept.id == conceptId
        })
        _proposals = Query(
            filter: #Predicate<ConceptUpdateProposal> { proposal in
                proposal.conceptId == conceptId
            },
            sort: \ConceptUpdateProposal.createdAt,
            order: .reverse
        )
    }

    private var concept: Concept? {
        concepts.first
    }

    private var activeProposal: ConceptUpdateProposal? {
        proposals.first { proposal in
            proposal.status == ProposalStatus.proposed.rawValue
        }
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
                        if let activeProposal {
                            proposalSection(activeProposal)
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

    private func proposalSection(_ proposal: ConceptUpdateProposal) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Label("Pending Update", systemImage: "checklist")
                    .font(.headline)
                Spacer()
                Text("\(Int(proposal.confidence * 100))%")
                    .font(.caption.weight(.medium))
                    .foregroundStyle(.secondary)
            }

            Text(proposal.rationale)
                .font(.body)
                .foregroundStyle(.primary)

            HStack(spacing: 10) {
                Button {
                    Task {
                        await mergeProposal(proposal)
                    }
                } label: {
                    if resolvingProposalId == proposal.id {
                        ProgressView()
                            .frame(maxWidth: .infinity)
                    } else {
                        Label("Confirm", systemImage: "checkmark")
                            .frame(maxWidth: .infinity)
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(resolvingProposalId != nil)

                Button {
                    Task {
                        await dismissProposal(proposal)
                    }
                } label: {
                    Label("Skip", systemImage: "xmark")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered)
                .disabled(resolvingProposalId != nil)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(.background, in: RoundedRectangle(cornerRadius: 8))
        .overlay {
            RoundedRectangle(cornerRadius: 8)
                .stroke(.orange.opacity(0.45), lineWidth: 1)
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
            let store = ConceptLocalStore(modelContext: modelContext)
            _ = try store.upsertConcept(from: response.concept)
            if let proposal = response.proposal {
                _ = try store.upsertProposal(proposal, conceptId: response.concept.id)
            }
            lastAnswer = response.answer
            followUpText = ""
        } catch {
            errorMessage = error.localizedDescription
        }
        isSubmittingFollowUp = false
    }

    private func mergeProposal(_ proposal: ConceptUpdateProposal) async {
        resolvingProposalId = proposal.id
        errorMessage = nil
        do {
            let concept = try await appServices.apiClient.mergeProposal(id: proposal.id)
            let store = ConceptLocalStore(modelContext: modelContext)
            _ = try store.upsertConcept(from: concept)
            try store.markProposal(id: proposal.id, status: .accepted)
        } catch {
            errorMessage = error.localizedDescription
        }
        resolvingProposalId = nil
    }

    private func dismissProposal(_ proposal: ConceptUpdateProposal) async {
        resolvingProposalId = proposal.id
        errorMessage = nil
        do {
            try await appServices.apiClient.dismissProposal(id: proposal.id)
            try ConceptLocalStore(modelContext: modelContext).markProposal(
                id: proposal.id,
                status: .dismissed
            )
        } catch {
            errorMessage = error.localizedDescription
        }
        resolvingProposalId = nil
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
