import Foundation
import SwiftData

@MainActor
struct CaptureFlowService {
    var localStore: ConceptLocalStore
    var apiClient: any SiftAPIClient

    func saveDraft(rawCapture: String) -> Concept? {
        let trimmed = rawCapture.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        return localStore.createDraft(rawCapture: trimmed, locale: inferredLocale(for: trimmed))
    }

    func resolveCapture(rawCapture: String) throws -> CaptureResolution {
        let trimmed = rawCapture.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return .empty }

        switch try localStore.findCaptureMatch(rawCapture: trimmed) {
        case .exact(let concept):
            return .existing(concept)
        case .ambiguous(let matches):
            let draft = localStore.createDisambiguationDraft(
                rawCapture: trimmed,
                locale: inferredLocale(for: trimmed)
            )
            return .needsDisambiguation(draft, matches: matches)
        case .none:
            let draft = localStore.createDraft(rawCapture: trimmed, locale: inferredLocale(for: trimmed))
            localStore.recordInitialCaptureQuestion(concept: draft, question: trimmed)
            return .newDraft(draft)
        }
    }

    func generateConcept(from draft: Concept) async throws -> Concept {
        draft.captureStatus = CaptureStatus.pendingGeneration.rawValue
        draft.updatedAt = .now
        let idempotencyKey = localStore.beginCaptureGeneration(for: draft)

        do {
            let request = CreateConceptRequest(rawCapture: draft.displayTitle, locale: draft.language)
            var dto: ConceptDTO?
            var streamedAnswer = ""
            for try await event in apiClient.streamCreateConcept(request, idempotencyKey: idempotencyKey) {
                if let delta = event.delta, !delta.isEmpty {
                    streamedAnswer += delta
                    localStore.appendInitialGenerationAnswerDelta(
                        concept: draft,
                        question: draft.displayTitle,
                        delta: delta
                    )
                }
                if let concept = event.concept {
                    dto = concept
                }
            }
            guard let dto else {
                throw SiftStreamingError.incomplete
            }
            let concept = try localStore.upsertConcept(from: dto)
            localStore.markCaptureGenerationCompleted(draft)
            let initialAnswer = dto.initialAnswer?.trimmingCharacters(in: .whitespacesAndNewlines)
            let conversationAnswer: String
            if let initialAnswer, !initialAnswer.isEmpty {
                conversationAnswer = initialAnswer
            } else {
                conversationAnswer = dto.oneLineExplanation
            }
            let finalConversationAnswer = preferredInitialConversationAnswer(
                streamed: streamedAnswer,
                final: conversationAnswer
            )
            localStore.replaceInitialGenerationAnswer(
                concept: concept,
                question: draft.displayTitle,
                answer: finalConversationAnswer
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

    private func preferredInitialConversationAnswer(streamed: String, final: String) -> String {
        let streamed = streamed.trimmingCharacters(in: .whitespacesAndNewlines)
        let final = final.trimmingCharacters(in: .whitespacesAndNewlines)
        if streamed.count > final.count * 2 {
            return streamed
        }
        return final.isEmpty ? streamed : final
    }

    private func inferredLocale(for text: String) -> String {
        if text.unicodeScalars.contains(where: { scalar in
            (0x4E00...0x9FFF).contains(Int(scalar.value))
        }) {
            return "zh-Hans"
        }
        return Locale.current.identifier
    }
}

enum CaptureResolution {
    case empty
    case existing(Concept)
    case newDraft(Concept)
    case needsDisambiguation(Concept, matches: [Concept])
}
