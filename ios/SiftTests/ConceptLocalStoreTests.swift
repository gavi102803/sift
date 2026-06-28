import SwiftData
import XCTest
@testable import Sift

@MainActor
final class ConceptLocalStoreTests: XCTestCase {
    func testGenerateFailureLeavesRecoverableDraft() async throws {
        let context = try makeModelContext()
        let store = ConceptLocalStore(modelContext: context)
        let service = CaptureFlowService(
            localStore: store,
            apiClient: TestAPIClient(
                createConceptResult: .failure(SiftAPIError.httpStatus(502, detail: nil))
            )
        )

        guard case .newDraft(let draft) = try service.resolveCapture(rawCapture: " Offline RAG ") else {
            return XCTFail("Expected a new local draft")
        }

        do {
            _ = try await service.generateConcept(from: draft)
            XCTFail("Expected generation to fail")
        } catch SiftAPIError.httpStatus {
            XCTAssertEqual(draft.displayTitle, "Offline RAG")
            XCTAssertEqual(draft.captureStatus, CaptureStatus.generationFailed.rawValue)
            XCTAssertNil(draft.captureGenerationIdempotencyKey)
        }

        let concepts = try context.fetch(FetchDescriptor<Concept>())
        XCTAssertEqual(concepts.count, 1)
        XCTAssertEqual(concepts.first?.id, draft.id)
        XCTAssertEqual(concepts.first?.captureStatus, CaptureStatus.generationFailed.rawValue)
    }

    func testCaptureGenerationKeySurvivesLocalReload() throws {
        let context = try makeModelContext()
        let store = ConceptLocalStore(modelContext: context)
        let draft = store.createDraft(rawCapture: "Agent runtime")
        let key = store.beginCaptureGeneration(for: draft)
        try context.save()

        let reloadedContext = ModelContext(context.container)
        let concepts = try reloadedContext.fetch(FetchDescriptor<Concept>())

        XCTAssertEqual(concepts.first?.captureGenerationIdempotencyKey, key.uuidString)
        XCTAssertEqual(
            concepts.first?.captureGenerationOperationStatus,
            LocalOperationStatus.inFlight.rawValue
        )
    }

    func testFailedFollowUpOperationIsNotReturnedAsTimelineTurn() throws {
        let context = try makeModelContext()
        let store = ConceptLocalStore(modelContext: context)
        let concept = store.createDraft(rawCapture: "RAG")

        store.recordInitialCaptureQuestion(concept: concept, question: "RAG")
        store.recordFailedFollowUpDraft(concept: concept, question: "retry me")

        let turns = store.localConversationTurns(for: concept)
        XCTAssertEqual(turns.map(\.content), ["RAG"])
    }

    func testSuccessfulGenerationReplacesLocalDraftWithRemoteConcept() async throws {
        let context = try makeModelContext()
        let store = ConceptLocalStore(modelContext: context)
        let remoteId = UUID()
        let service = CaptureFlowService(
            localStore: store,
            apiClient: TestAPIClient(
                createConceptResult: .success(
                    ConceptDTO(
                        id: remoteId,
                        canonicalTitle: "RAG evaluation",
                        displayTitle: "RAG evaluation",
                        oneLineExplanation: "Measures retrieval-augmented answer quality.",
                        maturity: ConceptMaturity.initial.rawValue,
                        captureStatus: CaptureStatus.ready.rawValue,
                        noteRevision: 1,
                        blocks: [
                            NoteBlockDTO(
                                id: UUID(),
                                blockType: NoteBlockType.whatItIs.rawValue,
                                content: "A repeatable check for RAG answer quality.",
                                source: NoteBlockSource.ai.rawValue,
                                isUserLocked: false
                            )
                        ],
                        tags: ["AI"],
                        topics: ["Evaluation"]
                    )
                )
            )
        )

        guard case .newDraft(let draft) = try service.resolveCapture(rawCapture: "RAG evaluation") else {
            return XCTFail("Expected a new local draft")
        }

        let generated = try await service.generateConcept(from: draft)
        try context.save()

        XCTAssertEqual(generated.id, remoteId)
        XCTAssertEqual(generated.captureStatus, CaptureStatus.ready.rawValue)

        let concepts = try context.fetch(FetchDescriptor<Concept>())
        XCTAssertEqual(concepts.count, 1)
        XCTAssertEqual(concepts.first?.id, remoteId)
        XCTAssertEqual(concepts.first?.displayTitle, "RAG evaluation")
    }

    func testManualNoteEditCreatesAuditRecordsAndLocksBlock() throws {
        let context = try makeModelContext()
        let store = ConceptLocalStore(modelContext: context)
        let concept = Concept(
            canonicalTitle: "RAG evaluation",
            displayTitle: "RAG evaluation",
            captureStatus: CaptureStatus.ready.rawValue,
            noteRevision: 2
        )
        let note = ConceptNote(revision: 2, concept: concept)
        let block = NoteBlock(
            blockType: NoteBlockType.whatItIs.rawValue,
            content: "AI generated note",
            source: NoteBlockSource.ai.rawValue,
            note: note
        )
        note.blocks = [block]
        concept.note = note
        context.insert(concept)

        try store.updateNoteBlock(block, content: "User refined note")
        try context.save()

        XCTAssertEqual(block.content, "User refined note")
        XCTAssertEqual(block.source, NoteBlockSource.user.rawValue)
        XCTAssertTrue(block.isUserLocked)
        XCTAssertEqual(block.lastEditedBy, UpdateActor.user.rawValue)
        XCTAssertEqual(concept.noteRevision, 3)
        XCTAssertEqual(note.revision, 3)

        let revisions = try context.fetch(FetchDescriptor<NoteRevision>())
        XCTAssertEqual(revisions.count, 1)
        XCTAssertEqual(revisions.first?.conceptId, concept.id)
        XCTAssertEqual(revisions.first?.revision, 3)
        XCTAssertEqual(revisions.first?.mergeMode, UpdateEventType.manualEdit.rawValue)
        XCTAssertTrue(revisions.first?.snapshotJSON.contains("User refined note") == true)

        let events = try context.fetch(FetchDescriptor<UpdateEvent>())
        XCTAssertEqual(events.count, 1)
        XCTAssertEqual(events.first?.conceptId, concept.id)
        XCTAssertEqual(events.first?.noteRevision, 3)
        XCTAssertEqual(events.first?.eventType, UpdateEventType.manualEdit.rawValue)
        XCTAssertEqual(events.first?.actor, UpdateActor.user.rawValue)
    }

    func testManualSummaryAndOrganizationEditPersistsAuditTagsAndTopics() throws {
        let context = try makeModelContext()
        let store = ConceptLocalStore(modelContext: context)
        let concept = Concept(
            canonicalTitle: "RAG",
            displayTitle: "RAG",
            oneLineExplanation: "Old explanation",
            captureStatus: CaptureStatus.ready.rawValue,
            noteRevision: 4
        )
        concept.note = ConceptNote(revision: 4, concept: concept)
        context.insert(concept)

        try store.updateConceptSummary(
            concept,
            displayTitle: "Retrieval Augmented Generation",
            oneLineExplanation: "Answers with retrieved context."
        )
        try store.replaceConceptTags(conceptId: concept.id, names: ["AI", "Retrieval"])
        try store.replaceConceptTopics(conceptId: concept.id, names: ["Machine Learning"])
        try context.save()

        XCTAssertEqual(concept.displayTitle, "Retrieval Augmented Generation")
        XCTAssertEqual(concept.canonicalTitle, "Retrieval Augmented Generation")
        XCTAssertEqual(concept.oneLineExplanation, "Answers with retrieved context.")
        XCTAssertEqual(concept.noteRevision, 5)
        XCTAssertEqual(concept.note?.revision, 5)

        let revisions = try context.fetch(FetchDescriptor<NoteRevision>())
        XCTAssertEqual(revisions.count, 1)
        XCTAssertEqual(revisions.first?.conceptId, concept.id)
        XCTAssertEqual(revisions.first?.revision, 5)
        XCTAssertTrue(revisions.first?.snapshotJSON.contains("Retrieval Augmented Generation") == true)

        let events = try context.fetch(FetchDescriptor<UpdateEvent>())
        XCTAssertEqual(events.count, 1)
        XCTAssertEqual(events.first?.eventType, UpdateEventType.manualEdit.rawValue)

        let tagNames = try context.fetch(FetchDescriptor<Tag>()).map(\.name).sorted()
        XCTAssertEqual(tagNames, ["AI", "Retrieval"])
        let topicNames = try context.fetch(FetchDescriptor<Topic>()).map(\.name)
        XCTAssertEqual(topicNames, ["Machine Learning"])
    }

    func testFailedFollowUpDraftsAreRecoverableDedupedAndClearable() throws {
        let context = try makeModelContext()
        let store = ConceptLocalStore(modelContext: context)
        let concept = Concept(
            canonicalTitle: "Context windows",
            displayTitle: "Context windows",
            captureStatus: CaptureStatus.ready.rawValue
        )
        context.insert(concept)

        store.recordFailedFollowUpDraft(concept: concept, question: "  Explain the tradeoff  ")
        store.recordFailedFollowUpDraft(concept: concept, question: "Explain the tradeoff")
        try context.save()

        XCTAssertEqual(store.latestFailedFollowUpDraft(for: concept), "Explain the tradeoff")

        let messages = try context.fetch(FetchDescriptor<ConversationMessage>())
        XCTAssertEqual(messages.count, 1)
        XCTAssertEqual(messages.first?.role, ConversationRole.user.rawValue)
        XCTAssertEqual(messages.first?.content, "Explain the tradeoff")
        XCTAssertEqual(messages.first?.updateMode, "failed")

        store.clearFailedFollowUpDrafts(for: concept, matching: "Explain the tradeoff")
        try context.save()

        XCTAssertNil(store.latestFailedFollowUpDraft(for: concept))
        XCTAssertTrue(try context.fetch(FetchDescriptor<ConversationMessage>()).isEmpty)
    }

    func testRemotePruneKeepsLocalFailureRecoveryDrafts() throws {
        let context = try makeModelContext()
        let store = ConceptLocalStore(modelContext: context)
        let failedLocalConcept = Concept(
            canonicalTitle: "Offline capture",
            displayTitle: "Offline capture",
            captureStatus: CaptureStatus.generationFailed.rawValue
        )
        let staleRemoteMirror = Concept(
            canonicalTitle: "Deleted remotely",
            displayTitle: "Deleted remotely",
            captureStatus: CaptureStatus.ready.rawValue
        )
        context.insert(failedLocalConcept)
        context.insert(staleRemoteMirror)

        try store.pruneLocalMirrorsMissingFromRemote(keeping: [])
        try context.save()

        let concepts = try context.fetch(FetchDescriptor<Concept>())
        XCTAssertTrue(concepts.contains { $0.id == failedLocalConcept.id })
        XCTAssertFalse(concepts.contains { $0.id == staleRemoteMirror.id })
    }

    func testStatusRulesSeparateLocalOnlyDraftsFromReadyConcepts() {
        XCTAssertTrue(ConceptStatusRules.isLocalOnly(CaptureStatus.draft.rawValue))
        XCTAssertTrue(ConceptStatusRules.isLocalOnly(CaptureStatus.pendingGeneration.rawValue))
        XCTAssertTrue(ConceptStatusRules.isLocalOnly(CaptureStatus.generating.rawValue))
        XCTAssertTrue(ConceptStatusRules.isLocalOnly(CaptureStatus.generationFailed.rawValue))
        XCTAssertFalse(ConceptStatusRules.isLocalOnly(CaptureStatus.ready.rawValue))
        XCTAssertFalse(ConceptStatusRules.canSubmitFollowUp(CaptureStatus.generating.rawValue))
        XCTAssertTrue(ConceptStatusRules.canSubmitFollowUp(CaptureStatus.ready.rawValue))
    }

    func testOrganizationDedupesTagsAndTopicsCaseInsensitively() throws {
        let context = try makeModelContext()
        let store = ConceptLocalStore(modelContext: context)
        let concept = Concept(
            canonicalTitle: "Embeddings",
            displayTitle: "Embeddings",
            captureStatus: CaptureStatus.ready.rawValue
        )
        context.insert(concept)

        try store.replaceConceptTags(conceptId: concept.id, names: ["AI", " ai ", "Retrieval"])
        try store.replaceConceptTopics(conceptId: concept.id, names: ["Machine Learning", "machine learning", "Search"])
        try context.save()

        let tags = try context.fetch(FetchDescriptor<Tag>()).map(\.name).sorted()
        XCTAssertEqual(tags, ["AI", "Retrieval"])
        let topics = try context.fetch(FetchDescriptor<Topic>()).map(\.name).sorted()
        XCTAssertEqual(topics, ["Machine Learning", "Search"])
        XCTAssertEqual(try context.fetch(FetchDescriptor<ConceptTag>()).count, 2)
        XCTAssertEqual(try context.fetch(FetchDescriptor<ConceptTopic>()).count, 2)
    }

    func testProposalAndRelationLifecycleArePersisted() throws {
        let context = try makeModelContext()
        let store = ConceptLocalStore(modelContext: context)
        let source = Concept(canonicalTitle: "RAG", displayTitle: "RAG", captureStatus: CaptureStatus.ready.rawValue)
        let target = Concept(
            canonicalTitle: "Embeddings",
            displayTitle: "Embeddings",
            captureStatus: CaptureStatus.ready.rawValue
        )
        context.insert(source)
        context.insert(target)

        let proposalId = UUID()
        let proposal = try store.upsertProposal(
            UpdateProposalDTO(
                id: proposalId,
                baseNoteRevision: 1,
                patchOperations: [
                    PatchOperationDTO(
                        operation: "appendBlock",
                        targetBlockId: nil,
                        content: "Add an example.",
                        oldValueHash: nil,
                        newContent: nil,
                        targetConceptId: nil,
                        relationType: nil
                    )
                ],
                rationale: "Clarify with an example.",
                confidence: 0.82,
                status: ProposalStatus.proposed.rawValue
            ),
            conceptId: source.id
        )
        XCTAssertEqual(proposal.status, ProposalStatus.proposed.rawValue)

        try store.markProposal(id: proposalId, status: .dismissed)
        XCTAssertEqual(proposal.status, ProposalStatus.dismissed.rawValue)
        XCTAssertNotNil(proposal.resolvedAt)

        try store.addRelation(sourceConceptId: source.id, targetConceptId: target.id)
        try store.addRelation(sourceConceptId: source.id, targetConceptId: target.id)
        var relations = try context.fetch(FetchDescriptor<ConceptRelation>())
        XCTAssertEqual(relations.count, 1)
        XCTAssertEqual(relations.first?.sourceConceptId, source.id)
        XCTAssertEqual(relations.first?.targetConceptId, target.id)
        XCTAssertEqual(relations.first?.status, "accepted")

        let relation = try XCTUnwrap(relations.first)
        store.removeRelation(relation)
        relations = try context.fetch(FetchDescriptor<ConceptRelation>())
        XCTAssertTrue(relations.isEmpty)
    }

    func testConceptSearchMatchesTitleExplanationAliasesTagsAndTopics() throws {
        let concept = Concept(
            canonicalTitle: "Retrieval Augmented Generation",
            displayTitle: "RAG",
            aliasesText: "Grounded generation, retrieve then answer",
            oneLineExplanation: "Improves answers by bringing external context into the prompt.",
            captureStatus: CaptureStatus.ready.rawValue
        )

        XCTAssertTrue(ConceptSearchIndex.matches(query: "rag", concept: concept, tags: [], topics: []))
        XCTAssertTrue(ConceptSearchIndex.matches(query: "retrieval augmented", concept: concept, tags: [], topics: []))
        XCTAssertTrue(ConceptSearchIndex.matches(query: "external context", concept: concept, tags: [], topics: []))
        XCTAssertTrue(ConceptSearchIndex.matches(query: "grounded", concept: concept, tags: [], topics: []))
        XCTAssertTrue(ConceptSearchIndex.matches(query: "retrieval", concept: concept, tags: ["AI Retrieval"], topics: []))
        XCTAssertTrue(ConceptSearchIndex.matches(query: "machine", concept: concept, tags: [], topics: ["Machine Learning"]))
        XCTAssertTrue(ConceptSearchIndex.matches(query: "  ", concept: concept, tags: [], topics: []))
        XCTAssertFalse(ConceptSearchIndex.matches(query: "spaced repetition", concept: concept, tags: [], topics: []))
    }

    private func makeModelContext() throws -> ModelContext {
        let schema = Schema([
            Concept.self,
            ConceptNote.self,
            NoteBlock.self,
            NoteRevision.self,
            UpdateEvent.self,
            Conversation.self,
            ModelThread.self,
            ConversationMessage.self,
            ConceptUpdateProposal.self,
            AnswerSource.self,
            Tag.self,
            ConceptTag.self,
            Topic.self,
            ConceptTopic.self,
            ConceptRelation.self
        ])
        let configuration = ModelConfiguration(schema: schema, isStoredInMemoryOnly: true)
        let container = try ModelContainer(for: schema, configurations: [configuration])
        return ModelContext(container)
    }
}

final class SiftAPIClientIdempotencyTests: XCTestCase {
    override func setUp() {
        super.setUp()
        URLProtocolRequestRecorder.reset()
        URLProtocolRequestRecorder.handler = { request in
            let path = request.url?.path ?? ""
            if path.hasSuffix("/turns/stream") {
                return HTTPURLProtocolResponse(
                    statusCode: 200,
                    contentType: "application/x-ndjson",
                    body: self.terminalStreamBody()
                )
            }
            return HTTPURLProtocolResponse(
                statusCode: 200,
                contentType: "application/json",
                body: self.responseBody(for: path)
            )
        }
    }

    func testCreateStreamAndMergeWriteProvidedIdempotencyHeader() async throws {
        let client = makeHTTPClient()
        let key = UUID(uuidString: "00000000-0000-0000-0000-00000000CAFE")!

        _ = try await client.createConcept(
            CreateConceptRequest(rawCapture: "RAG", locale: "en"),
            idempotencyKey: key
        )
        let stream = client.streamTurn(
            conceptId: UUID(uuidString: "00000000-0000-0000-0000-000000000111")!,
            request: ConceptTurnRequest(question: "How does it work?"),
            idempotencyKey: key
        )
        var streamEvents: [ConceptTurnStreamEvent] = []
        for try await event in stream {
            streamEvents.append(event)
        }
        _ = try await client.mergeProposal(
            id: UUID(uuidString: "00000000-0000-0000-0000-000000000222")!,
            idempotencyKey: key
        )

        let requests = URLProtocolRequestRecorder.requests()
        XCTAssertEqual(streamEvents.map(\.type), ["completed"])
        XCTAssertEqual(
            requests.map { $0.value(forHTTPHeaderField: "Idempotency-Key") },
            [key.uuidString, key.uuidString, key.uuidString]
        )
    }

    func testGetAndPatchDoNotWriteIdempotencyHeader() async throws {
        let client = makeHTTPClient()
        let conceptId = UUID(uuidString: "00000000-0000-0000-0000-000000000111")!

        _ = try await client.getConcept(id: conceptId)
        _ = try await client.updateConceptSummary(
            id: conceptId,
            request: UpdateConceptSummaryRequest(
                displayTitle: "RAG",
                oneLineExplanation: "Updated."
            )
        )

        let requests = URLProtocolRequestRecorder.requests()
        XCTAssertEqual(requests.map(\.httpMethod), ["GET", "PATCH"])
        XCTAssertEqual(
            requests.map { $0.value(forHTTPHeaderField: "Idempotency-Key") },
            [nil, nil]
        )
    }

    private func makeHTTPClient() -> HTTPSiftAPIClient {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [URLProtocolRequestRecorder.self]
        return HTTPSiftAPIClient(
            baseURL: URL(string: "http://127.0.0.1:8000")!,
            urlSession: URLSession(configuration: configuration)
        )
    }

    private func responseBody(for path: String) -> Data {
        if path.contains("/turns") {
            return encoded(turnResponse())
        }
        return encoded(conceptDTO())
    }

    private func terminalStreamBody() -> Data {
        let event = ConceptTurnStreamEvent(type: "completed", delta: nil, response: turnResponse())
        return encoded(event) + Data("\n".utf8)
    }

    private func turnResponse() -> ConceptTurnResponse {
        ConceptTurnResponse(
            answer: "A terminal answer.",
            answerSource: AnswerSourceDTO(
                sourceType: AnswerSourceType.modelKnowledge.rawValue,
                confidence: 0.5,
                uncertaintyNote: "Test response."
            ),
            updateMode: UpdateMode.none.rawValue,
            concept: conceptDTO(),
            proposal: nil
        )
    }

    private func conceptDTO() -> ConceptDTO {
        ConceptDTO(
            id: UUID(uuidString: "00000000-0000-0000-0000-000000000111")!,
            canonicalTitle: "RAG",
            displayTitle: "RAG",
            oneLineExplanation: "Retrieval augmented generation.",
            maturity: ConceptMaturity.initial.rawValue,
            captureStatus: CaptureStatus.ready.rawValue,
            noteRevision: 1,
            blocks: []
        )
    }

    private func encoded<T: Encodable>(_ value: T) -> Data {
        try! JSONEncoder().encode(value)
    }
}

private struct HTTPURLProtocolResponse {
    var statusCode: Int
    var contentType: String
    var body: Data
}

private final class URLProtocolRequestRecorder: URLProtocol {
    nonisolated(unsafe) static var handler: ((URLRequest) -> HTTPURLProtocolResponse)?
    private nonisolated(unsafe) static var recordedRequests: [URLRequest] = []
    private nonisolated(unsafe) static var lock = NSLock()

    static func reset() {
        lock.lock()
        recordedRequests = []
        handler = nil
        lock.unlock()
    }

    static func requests() -> [URLRequest] {
        lock.lock()
        defer { lock.unlock() }
        return recordedRequests
    }

    override class func canInit(with request: URLRequest) -> Bool {
        true
    }

    override class func canonicalRequest(for request: URLRequest) -> URLRequest {
        request
    }

    override func startLoading() {
        Self.lock.lock()
        Self.recordedRequests.append(request)
        let handler = Self.handler
        Self.lock.unlock()

        guard let response = handler?(request),
              let url = request.url,
              let httpResponse = HTTPURLResponse(
                url: url,
                statusCode: response.statusCode,
                httpVersion: nil,
                headerFields: ["Content-Type": response.contentType]
              ) else {
            client?.urlProtocol(self, didFailWithError: URLError(.badServerResponse))
            return
        }

        client?.urlProtocol(self, didReceive: httpResponse, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: response.body)
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}
}

private enum TestError: Error {
    case expectedFailure
    case unimplemented
}

private struct TestAPIClient: SiftAPIClient {
    var createConceptResult: Result<ConceptDTO, Error>
    var createConceptIdempotencyKey: UUID?

    var backendDescription: String {
        "test"
    }

    func getAppStatus() async throws -> AppStatusDTO {
        throw TestError.unimplemented
    }

    func getModelProviderSettings() async throws -> ModelProviderSettingsDTO {
        throw TestError.unimplemented
    }

    func updateModelProviderSettings(
        _ request: UpdateModelProviderSettingsRequest
    ) async throws -> ModelProviderSettingsDTO {
        throw TestError.unimplemented
    }

    func listRuntimeModelProviders() async throws -> RuntimeProviderCatalogDTO {
        throw TestError.unimplemented
    }

    func listRuntimeWebProviders() async throws -> WebProviderCatalogDTO {
        throw TestError.unimplemented
    }

    func getWebProviderSettings() async throws -> WebProviderSettingsDTO {
        throw TestError.unimplemented
    }

    func updateWebProviderSettings(
        _ request: UpdateWebProviderSettingsRequest
    ) async throws -> WebProviderSettingsDTO {
        throw TestError.unimplemented
    }

    func listProviderModels() async throws -> ProviderModelListDTO {
        throw TestError.unimplemented
    }

    func runModelDiagnostic() async throws -> ModelDiagnosticDTO {
        throw TestError.unimplemented
    }

    func runWebSearchDiagnostic() async throws -> ModelDiagnosticDTO {
        throw TestError.unimplemented
    }

    func listConcepts() async throws -> [ConceptDTO] {
        throw TestError.unimplemented
    }

    func getConcept(id: UUID) async throws -> ConceptDTO {
        throw TestError.unimplemented
    }

    func updateConceptSummary(id: UUID, request: UpdateConceptSummaryRequest) async throws -> ConceptDTO {
        throw TestError.unimplemented
    }

    func updateNoteBlock(
        conceptId: UUID,
        blockId: UUID,
        request: UpdateNoteBlockRequest
    ) async throws -> ConceptDTO {
        throw TestError.unimplemented
    }

    func updateConceptNote(
        id: UUID,
        request: UpdateConceptNoteRequest
    ) async throws -> ConceptDTO {
        throw TestError.unimplemented
    }

    func updateConceptOrganization(
        id: UUID,
        request: UpdateConceptOrganizationRequest
    ) async throws -> ConceptDTO {
        throw TestError.unimplemented
    }

    func addRelation(conceptId: UUID, request: CreateConceptRelationRequest) async throws -> ConceptDTO {
        throw TestError.unimplemented
    }

    func removeRelation(conceptId: UUID, relationId: UUID) async throws -> ConceptDTO {
        throw TestError.unimplemented
    }

    func listTurns(conceptId: UUID) async throws -> [ConceptHistoryTurnDTO] {
        throw TestError.unimplemented
    }

    func createConcept(_ request: CreateConceptRequest) async throws -> ConceptDTO {
        try await createConcept(request, idempotencyKey: nil)
    }

    func createConcept(
        _ request: CreateConceptRequest,
        idempotencyKey: UUID?
    ) async throws -> ConceptDTO {
        switch createConceptResult {
        case .success(let dto):
            return dto
        case .failure(let error):
            throw error
        }
    }

    func submitTurn(conceptId: UUID, request: ConceptTurnRequest) async throws -> ConceptTurnResponse {
        throw TestError.unimplemented
    }

    func streamTurn(
        conceptId: UUID,
        request: ConceptTurnRequest
    ) -> AsyncThrowingStream<ConceptTurnStreamEvent, Error> {
        AsyncThrowingStream { continuation in
            continuation.finish(throwing: TestError.unimplemented)
        }
    }

    func mergeProposal(id: UUID) async throws -> ConceptDTO {
        throw TestError.unimplemented
    }

    func dismissProposal(id: UUID) async throws {
        throw TestError.unimplemented
    }
}
