import Foundation
import SwiftData

struct ReconciledCaptureGenerationFailure: LocalizedError {
    let underlying: Error
    let conceptId: UUID

    var errorDescription: String? { underlying.localizedDescription }
}

private struct TerminalInitialFailureReconciliation {
    let replacementConceptId: UUID?
}

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

    func generateConcept(
        from draft: Concept,
        onProgress: (String) -> Void = { _ in }
    ) async throws -> Concept {
        draft.captureStatus = CaptureStatus.pendingGeneration.rawValue
        draft.updatedAt = .now
        let idempotencyKey = localStore.beginCaptureGeneration(for: draft)
        let recoverableRunId = localStore.recoverableCaptureRunId(for: draft)
        localStore.clearInitialGenerationAnswer(concept: draft)
        localStore.clearInitialGenerationSources(concept: draft)
        // The question and its idempotency key must be durable before any
        // fallible model/network work begins. This also gives SwiftData a
        // stable graph before streamed messages are later reconciled.
        try localStore.modelContext.save()

        var activeRunID: UUID?
        do {
            let request = CreateConceptRequest(rawCapture: draft.displayTitle, locale: draft.language)
            var dto: ConceptDTO?
            var streamedAnswer = ""
            var streamedCitations: [CitationDTO] = []
            var answerIdleTask: Task<Void, Never>?
            var textSmoother = StreamingTextSmoother { fragment in
                streamedAnswer += fragment
                localStore.appendInitialGenerationAnswerDelta(
                    concept: draft,
                    question: draft.displayTitle,
                    delta: fragment
                )
            }
            defer {
                answerIdleTask?.cancel()
                textSmoother.cancel()
            }
            let stream: AsyncThrowingStream<ConceptInitialStreamEvent, Error>
            if let recoverableRunId {
                stream = apiClient.streamResumeInitialConceptRun(id: recoverableRunId)
            } else {
                stream = apiClient.streamCreateConcept(
                    request,
                    idempotencyKey: idempotencyKey,
                    clientDraftId: draft.id
                )
            }
            for try await event in stream {
                if let progressLabel = event.progressLabel {
                    onProgress(progressLabel)
                }
                if let run = event.modelRun {
                    activeRunID = run.id
                    try localStore.upsertModelRun(run, lastSequence: event.sequence)
                }
                if event.type == "reset" {
                    answerIdleTask?.cancel()
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
                    answerIdleTask?.cancel()
                    textSmoother.append(delta)
                    let activeSmoother = textSmoother
                    answerIdleTask = Task { @MainActor in
                        do {
                            // Some live execution streams deliver answer deltas
                            // and terminal state but omit the later structure
                            // progress event. Treat a quiet answer stream as a
                            // presentation boundary only; the backend remains
                            // authoritative for actual run completion.
                            try await Task.sleep(for: .milliseconds(1_500))
                            try await activeSmoother.finish()
                            try Task.checkCancellation()
                            localStore.markInitialGenerationBuildingCard(concept: draft)
                        } catch {
                            return
                        }
                    }
                }
                if let citations = event.citations, !citations.isEmpty {
                    streamedCitations = citations
                    localStore.recordInitialGenerationSources(
                        concept: draft,
                        citations: citations
                    )
                }
                if event.progressLabel != nil, !streamedAnswer.isEmpty {
                    answerIdleTask?.cancel()
                    try await textSmoother.finish()
                    localStore.markInitialGenerationBuildingCard(concept: draft)
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
            if dto.answerSource?.citations?.isEmpty != false, !streamedCitations.isEmpty {
                localStore.recordInitialGenerationSources(
                    concept: concept,
                    citations: streamedCitations
                )
            }
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
            if isModelRunFailure(error),
               let activeRunID,
               let reconciliation = await reconcileTerminalInitialFailure(runID: activeRunID) {
                if let conceptId = reconciliation.replacementConceptId {
                    throw ReconciledCaptureGenerationFailure(
                        underlying: error,
                        conceptId: conceptId
                    )
                }
                throw error
            }
            if isTerminalGenerationFailure(error) {
                localStore.markCaptureGenerationTerminalFailure(
                    draft,
                    error: error,
                    preserveIdempotencyKey: isModelRunFailure(error)
                )
            } else {
                localStore.markCaptureGenerationUnknown(draft)
            }
            throw error
        }
    }

    func retryGeneration(
        for concept: Concept,
        onProgress: (String) -> Void = { _ in }
    ) async throws -> Concept {
        try await generateConcept(from: concept, onProgress: onProgress)
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

    private func isModelRunFailure(_ error: Error) -> Bool {
        if case SiftAPIError.modelRunFailed = error { return true }
        return false
    }

    private func reconcileTerminalInitialFailure(
        runID: UUID
    ) async -> TerminalInitialFailureReconciliation? {
        guard let run = try? await apiClient.getModelRun(id: runID),
              run.kind == "initialConcept",
              run.status == "failed" else { return nil }
        do {
            _ = try localStore.upsertModelRun(run)
            let remoteConcept: ConceptDTO?
            if let conceptId = run.conceptId {
                remoteConcept = try? await apiClient.getConcept(id: conceptId)
            } else {
                remoteConcept = nil
            }
            try localStore.reconcileFailedModelRun(run, remoteConcept: remoteConcept)
            try localStore.modelContext.save()
            return TerminalInitialFailureReconciliation(
                replacementConceptId: remoteConcept?.id
            )
        } catch {
            return nil
        }
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
