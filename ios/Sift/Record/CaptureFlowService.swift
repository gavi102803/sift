import Foundation
import SwiftData

@MainActor
struct CaptureFlowService {
    var localStore: ConceptLocalStore
    var apiClient: any SiftAPIClient

    func saveDraft(rawCapture: String) -> Concept? {
        let trimmed = rawCapture.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        return localStore.createDraft(rawCapture: trimmed)
    }

    func resolveCapture(rawCapture: String) throws -> CaptureResolution {
        let trimmed = rawCapture.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return .empty }

        switch try localStore.findCaptureMatch(rawCapture: trimmed) {
        case .exact(let concept):
            return .existing(concept)
        case .ambiguous(let matches):
            let draft = localStore.createDisambiguationDraft(rawCapture: trimmed)
            return .needsDisambiguation(draft, matches: matches)
        case .none:
            let draft = localStore.createDraft(rawCapture: trimmed)
            localStore.recordInitialCaptureQuestion(concept: draft, question: trimmed)
            return .newDraft(draft)
        }
    }

    func generateConcept(from draft: Concept) async throws -> Concept {
        draft.captureStatus = CaptureStatus.pendingGeneration.rawValue
        draft.updatedAt = .now
        let idempotencyKey = localStore.beginCaptureGeneration(for: draft)

        do {
            let dto = try await apiClient.createConcept(
                CreateConceptRequest(rawCapture: draft.displayTitle, locale: draft.language),
                idempotencyKey: idempotencyKey
            )
            let concept = try localStore.upsertConcept(from: dto)
            localStore.markCaptureGenerationCompleted(draft)
            localStore.recordInitialGenerationAnswer(
                concept: concept,
                question: draft.displayTitle,
                answer: dto.oneLineExplanation
            )
            if draft.id != concept.id {
                localStore.deleteConcept(draft)
            }
            return concept
        } catch {
            if isTerminalGenerationFailure(error) {
                localStore.markCaptureGenerationTerminalFailure(draft, error: error)
            } else {
                localStore.markCaptureGenerationUnknown(draft)
            }
            throw error
        }
    }

    func retryGeneration(for concept: Concept) async throws -> Concept {
        try await generateConcept(from: concept)
    }

    private func isTerminalGenerationFailure(_ error: Error) -> Bool {
        if case SiftAPIError.httpStatus = error {
            return true
        }
        if error is URLError {
            return false
        }
        return false
    }
}

enum CaptureResolution {
    case empty
    case existing(Concept)
    case newDraft(Concept)
    case needsDisambiguation(Concept, matches: [Concept])
}
