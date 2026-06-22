import Foundation

struct MockSiftAPIClient: SiftAPIClient {
    var delayNanoseconds: UInt64 = 250_000_000

    func listConcepts() async throws -> [ConceptDTO] {
        try await Task.sleep(nanoseconds: delayNanoseconds)
        return []
    }

    func getConcept(id: UUID) async throws -> ConceptDTO {
        try await Task.sleep(nanoseconds: delayNanoseconds)
        return ConceptDTO(
            id: id,
            canonicalTitle: "RAG",
            displayTitle: "RAG",
            oneLineExplanation: "Retrieval-augmented generation improves answers with retrieved context.",
            maturity: ConceptMaturity.growing.rawValue,
            captureStatus: CaptureStatus.ready.rawValue,
            noteRevision: 1,
            blocks: []
        )
    }

    func createConcept(_ request: CreateConceptRequest) async throws -> ConceptDTO {
        try await Task.sleep(nanoseconds: delayNanoseconds)

        return ConceptDTO(
            id: UUID(),
            canonicalTitle: request.rawCapture.trimmingCharacters(in: .whitespacesAndNewlines),
            displayTitle: request.rawCapture.trimmingCharacters(in: .whitespacesAndNewlines),
            oneLineExplanation: "A first-pass explanation generated for local preview.",
            maturity: ConceptMaturity.initial.rawValue,
            captureStatus: CaptureStatus.ready.rawValue,
            noteRevision: 1,
            blocks: [
                NoteBlockDTO(
                    id: UUID(),
                    blockType: NoteBlockType.whatItIs.rawValue,
                    content: "A concise explanation will appear here.",
                    source: NoteBlockSource.ai.rawValue,
                    isUserLocked: false
                ),
                NoteBlockDTO(
                    id: UUID(),
                    blockType: NoteBlockType.whyItMatters.rawValue,
                    content: "Sift keeps this concept available for future follow-up.",
                    source: NoteBlockSource.ai.rawValue,
                    isUserLocked: false
                )
            ]
        )
    }

    func submitTurn(conceptId: UUID, request: ConceptTurnRequest) async throws -> ConceptTurnResponse {
        try await Task.sleep(nanoseconds: delayNanoseconds)

        let concept = ConceptDTO(
            id: conceptId,
            canonicalTitle: "RAG",
            displayTitle: "RAG",
            oneLineExplanation: "Retrieval-augmented generation improves answers with retrieved context.",
            maturity: ConceptMaturity.growing.rawValue,
            captureStatus: CaptureStatus.ready.rawValue,
            noteRevision: 2,
            blocks: []
        )

        return ConceptTurnResponse(
            answer: "RAG differs from fine-tuning because it retrieves external context at answer time.",
            answerSource: AnswerSourceDTO(
                sourceType: AnswerSourceType.modelKnowledge.rawValue,
                confidence: 0.72,
                uncertaintyNote: "Generated from model knowledge, no external sources cited."
            ),
            updateMode: UpdateMode.autoMerge.rawValue,
            concept: concept,
            proposal: nil
        )
    }

    func mergeProposal(id: UUID) async throws -> ConceptDTO {
        try await Task.sleep(nanoseconds: delayNanoseconds)

        return ConceptDTO(
            id: UUID(),
            canonicalTitle: "Merged Concept",
            displayTitle: "Merged Concept",
            oneLineExplanation: "Proposal merged.",
            maturity: ConceptMaturity.growing.rawValue,
            captureStatus: CaptureStatus.ready.rawValue,
            noteRevision: 2,
            blocks: []
        )
    }

    func dismissProposal(id: UUID) async throws {
        try await Task.sleep(nanoseconds: delayNanoseconds)
    }
}
