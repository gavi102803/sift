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
        localStore.clearInitialGenerationAnswer(concept: draft)
        // The question and its idempotency key must be durable before any
        // fallible model/network work begins. This also gives SwiftData a
        // stable graph before streamed messages are later reconciled.
        try localStore.modelContext.save()

        var activeRunID: UUID?
        do {
            let request = CreateConceptRequest(rawCapture: draft.displayTitle, locale: draft.language)
            var dto: ConceptDTO?
            var streamedAnswer = ""
            var textSmoother = StreamingTextSmoother { fragment in
                streamedAnswer += fragment
                localStore.appendInitialGenerationAnswerDelta(
                    concept: draft,
                    question: draft.displayTitle,
                    delta: fragment
                )
            }
            defer { textSmoother.cancel() }
            for try await event in apiClient.streamCreateConcept(
                request,
                idempotencyKey: idempotencyKey,
                clientDraftId: draft.id
            ) {
                if let run = event.modelRun {
                    activeRunID = run.id
                    try localStore.upsertModelRun(run, lastSequence: event.sequence)
                }
                if event.type == "reset" {
                    textSmoother.cancel()
                    streamedAnswer = ""
                    localStore.clearInitialGenerationAnswer(concept: draft)
                    textSmoother = StreamingTextSmoother { fragment in
                        streamedAnswer += fragment
                        localStore.appendInitialGenerationAnswerDelta(
                            concept: draft,
                            question: draft.displayTitle,
                            delta: fragment
                        )
                    }
                }
                if let delta = event.delta, !delta.isEmpty {
                    textSmoother.append(delta)
                }
                if let concept = event.concept {
                    dto = concept
                }
            }
            try await textSmoother.finish()
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
        } catch is CancellationError {
            if let activeRunID {
                _ = await Task {
                    try? await apiClient.cancelModelRun(id: activeRunID)
                }.value
            }
            localStore.markCaptureGenerationUnknown(draft)
            throw CancellationError()
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
        if case SiftAPIError.httpStatus(let status, _) = error {
            return (400...499).contains(status)
        }
        if case SiftAPIError.modelRunFailed = error {
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
