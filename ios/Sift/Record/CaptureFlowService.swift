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

    func generateConcept(from draft: Concept) async throws -> Concept {
        draft.captureStatus = CaptureStatus.pendingGeneration.rawValue
        draft.updatedAt = .now

        do {
            draft.captureStatus = CaptureStatus.generating.rawValue
            let dto = try await apiClient.createConcept(
                CreateConceptRequest(rawCapture: draft.displayTitle, locale: draft.language)
            )
            return try localStore.upsertConcept(from: dto)
        } catch {
            draft.captureStatus = CaptureStatus.generationFailed.rawValue
            draft.updatedAt = .now
            throw error
        }
    }
}
