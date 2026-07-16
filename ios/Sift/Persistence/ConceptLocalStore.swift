import Foundation
import SwiftData

@MainActor
struct ConceptLocalStore {
    var modelContext: ModelContext

    func createDraft(rawCapture: String, locale: String = Locale.current.identifier) -> Concept {
        let title = rawCapture.trimmingCharacters(in: .whitespacesAndNewlines)
        let concept = Concept(
            canonicalTitle: title,
            displayTitle: title,
            language: locale,
            captureStatus: CaptureStatus.draft.rawValue
        )
        modelContext.insert(concept)
        return concept
    }

    func recordInitialCaptureQuestion(concept: Concept, question: String) {
        let trimmedQuestion = question.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedQuestion.isEmpty else { return }
        let conversation = ensureConversation(for: concept)
        conversation.initialQuery = trimmedQuestion
        conversation.updatedAt = .now
        if conversation.messages.contains(where: { message in
            message.role == ConversationRole.user.rawValue
                && message.content == trimmedQuestion
                && message.updateMode == initialCaptureUpdateMode
        }) {
            return
        }
        modelContext.insert(
            ConversationMessage(
                role: ConversationRole.user.rawValue,
                content: trimmedQuestion,
                createdAt: .now,
                updateMode: initialCaptureUpdateMode,
                conversation: conversation
            )
        )
    }

    func recordInitialGenerationAnswer(concept: Concept, question: String, answer: String) {
        recordInitialCaptureQuestion(concept: concept, question: question)
        let trimmedAnswer = answer.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedAnswer.isEmpty else { return }
        let conversation = ensureConversation(for: concept)
        if conversation.messages.contains(where: { message in
            message.role == ConversationRole.assistant.rawValue
                && message.updateMode == initialCaptureUpdateMode
        }) {
            return
        }
        modelContext.insert(
            ConversationMessage(
                role: ConversationRole.assistant.rawValue,
                content: trimmedAnswer,
                createdAt: .now,
                updateMode: initialCaptureUpdateMode,
                operationStatus: "completed",
                conversation: conversation
            )
        )
    }

    func appendInitialGenerationAnswerDelta(concept: Concept, question: String, delta: String) {
        recordInitialCaptureQuestion(concept: concept, question: question)
        guard !delta.isEmpty else { return }
        let conversation = ensureConversation(for: concept)
        if let message = conversation.messages
            .filter({
                $0.role == ConversationRole.assistant.rawValue
                    && $0.updateMode == initialCaptureUpdateMode
            })
            .sorted(by: { $0.createdAt < $1.createdAt })
            .last {
            message.content += delta
            message.operationStatus = "streaming"
            conversation.updatedAt = .now
            return
        }
        modelContext.insert(
            ConversationMessage(
                role: ConversationRole.assistant.rawValue,
                content: delta,
                createdAt: .now,
                updateMode: initialCaptureUpdateMode,
                operationStatus: "streaming",
                conversation: conversation
            )
        )
    }

    func replaceInitialGenerationAnswer(concept: Concept, question: String, answer: String) {
        recordInitialCaptureQuestion(concept: concept, question: question)
        let trimmedAnswer = answer.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedAnswer.isEmpty else { return }
        let conversation = ensureConversation(for: concept)
        if let message = conversation.messages
            .filter({
                $0.role == ConversationRole.assistant.rawValue
                    && $0.updateMode == initialCaptureUpdateMode
            })
            .sorted(by: { $0.createdAt < $1.createdAt })
            .last {
            message.content = trimmedAnswer
            message.operationStatus = "completed"
            conversation.updatedAt = .now
            return
        }
        recordInitialGenerationAnswer(concept: concept, question: question, answer: trimmedAnswer)
    }

    func replaceInitialExchange(concept: Concept, question: String, answer: String) {
        let conversation = ensureConversation(for: concept)
        for message in conversation.messages where message.updateMode == initialCaptureUpdateMode {
            modelContext.delete(message)
        }
        conversation.initialQuery = question
        conversation.updatedAt = .now
        modelContext.insert(
            ConversationMessage(
                role: ConversationRole.user.rawValue,
                content: question,
                createdAt: .now,
                updateMode: initialCaptureUpdateMode,
                operationStatus: "completed",
                conversation: conversation
            )
        )
        modelContext.insert(
            ConversationMessage(
                role: ConversationRole.assistant.rawValue,
                content: answer,
                createdAt: .now.addingTimeInterval(0.001),
                updateMode: initialCaptureUpdateMode,
                operationStatus: "completed",
                conversation: conversation
            )
        )
    }

    func recordInitialGenerationFailure(concept: Concept, error: Error) {
        let conversation = ensureConversation(for: concept)
        conversation.updatedAt = .now
        let message = "Generation failed: \(error.localizedDescription)"
        if conversation.messages.contains(where: { existing in
            existing.role == ConversationRole.assistant.rawValue
                && existing.content == message
                && existing.updateMode == failedFollowUpUpdateMode
        }) {
            return
        }
        modelContext.insert(
            ConversationMessage(
                role: ConversationRole.assistant.rawValue,
                content: message,
                createdAt: .now,
                updateMode: failedFollowUpUpdateMode,
                conversation: conversation
            )
        )
    }

    func localConversationTurns(for concept: Concept) -> [ConceptHistoryTurnDTO] {
        guard let conversation = concept.conversation else { return [] }
        return conversation.messages
            .sorted { $0.createdAt < $1.createdAt }
            .filter { message in
                message.updateMode != failedFollowUpUpdateMode
            }
            .map { message in
                ConceptHistoryTurnDTO(
                    id: message.id,
                    role: message.role,
                    content: message.content,
                    answerSource: nil,
                    status: "completed"
                )
            }
    }

    func findCaptureMatch(rawCapture: String) throws -> CaptureMatchResult {
        let normalizedCapture = normalizedLookupKey(rawCapture)
        guard !normalizedCapture.isEmpty else { return .none }

        let concepts = try modelContext.fetch(FetchDescriptor<Concept>())
            .filter { $0.captureStatus != CaptureStatus.archived.rawValue }
        let exactMatches = concepts.filter { concept in
            lookupKeys(for: concept).contains(normalizedCapture)
        }
        if let exactMatch = exactMatches.sorted(by: { $0.updatedAt > $1.updatedAt }).first {
            return .exact(exactMatch)
        }

        let ambiguousMatches = concepts.filter { concept in
            lookupKeys(for: concept).contains { key in
                key.contains(normalizedCapture) || normalizedCapture.contains(key)
            }
        }
        if ambiguousMatches.count > 1 {
            return .ambiguous(ambiguousMatches)
        }

        return .none
    }

    func createDisambiguationDraft(rawCapture: String, locale: String = Locale.current.identifier) -> Concept {
        let concept = createDraft(rawCapture: rawCapture, locale: locale)
        concept.captureStatus = CaptureStatus.needsDisambiguation.rawValue
        concept.oneLineExplanation = "Review possible existing concepts before generating."
        concept.updatedAt = .now
        return concept
    }

    func beginCaptureGeneration(for concept: Concept) -> UUID {
        if let existing = concept.captureGenerationIdempotencyKey,
           let uuid = UUID(uuidString: existing),
           concept.captureGenerationOperationStatus != LocalOperationStatus.failed.rawValue,
           concept.captureGenerationOperationStatus != LocalOperationStatus.completed.rawValue {
            concept.captureStatus = CaptureStatus.generating.rawValue
            concept.captureGenerationOperationStatus = LocalOperationStatus.inFlight.rawValue
            concept.updatedAt = .now
            return uuid
        }

        let key = UUID()
        concept.captureGenerationIdempotencyKey = key.uuidString
        concept.captureGenerationOperationStatus = LocalOperationStatus.inFlight.rawValue
        concept.captureStatus = CaptureStatus.generating.rawValue
        concept.updatedAt = .now
        return key
    }

    func markCaptureGenerationUnknown(_ concept: Concept) {
        concept.captureStatus = CaptureStatus.pendingGeneration.rawValue
        concept.captureGenerationOperationStatus = LocalOperationStatus.pending.rawValue
        concept.updatedAt = .now
    }

    func markCaptureGenerationTerminalFailure(_ concept: Concept, error: Error) {
        concept.captureStatus = CaptureStatus.generationFailed.rawValue
        concept.captureGenerationOperationStatus = LocalOperationStatus.failed.rawValue
        concept.captureGenerationIdempotencyKey = nil
        concept.updatedAt = .now
        recordInitialGenerationFailure(concept: concept, error: error)
    }

    func markCaptureGenerationCompleted(_ concept: Concept) {
        concept.captureGenerationOperationStatus = LocalOperationStatus.completed.rawValue
        concept.captureGenerationIdempotencyKey = nil
        concept.updatedAt = .now
    }

    func reserveFollowUpOperation(concept: Concept, question: String) -> UUID {
        let conversation = ensureConversation(for: concept)
        if let existing = conversation.pendingFollowUpIdempotencyKey,
           let uuid = UUID(uuidString: existing),
           conversation.pendingFollowUpQuestion == question,
           conversation.pendingFollowUpOperationStatus != LocalOperationStatus.failed.rawValue,
           conversation.pendingFollowUpOperationStatus != LocalOperationStatus.completed.rawValue {
            conversation.pendingFollowUpOperationStatus = LocalOperationStatus.inFlight.rawValue
            conversation.updatedAt = .now
            return uuid
        }

        let key = UUID()
        conversation.pendingFollowUpIdempotencyKey = key.uuidString
        conversation.pendingFollowUpQuestion = question
        conversation.pendingFollowUpOperationStatus = LocalOperationStatus.inFlight.rawValue
        conversation.updatedAt = .now
        return key
    }

    func markFollowUpOperationFailed(concept: Concept, question: String, key: UUID) {
        let conversation = ensureConversation(for: concept)
        conversation.pendingFollowUpIdempotencyKey = key.uuidString
        conversation.pendingFollowUpQuestion = question
        conversation.pendingFollowUpOperationStatus = LocalOperationStatus.failed.rawValue
        conversation.updatedAt = .now
    }

    func clearFollowUpOperation(concept: Concept, key: UUID) {
        let conversation = ensureConversation(for: concept)
        guard conversation.pendingFollowUpIdempotencyKey == key.uuidString else { return }
        conversation.pendingFollowUpOperationStatus = LocalOperationStatus.completed.rawValue
        conversation.pendingFollowUpIdempotencyKey = nil
        conversation.pendingFollowUpQuestion = nil
        conversation.updatedAt = .now
    }

    func upsertConcept(from dto: ConceptDTO) throws -> Concept {
        let existingConcept = try fetchConcept(id: dto.id)
        let concept = existingConcept ?? Concept(
            id: dto.id,
            canonicalTitle: dto.canonicalTitle,
            displayTitle: dto.displayTitle
        )

        concept.canonicalTitle = dto.canonicalTitle
        concept.displayTitle = dto.displayTitle
        concept.oneLineExplanation = dto.oneLineExplanation
        concept.maturity = dto.maturity
        concept.captureStatus = dto.captureStatus
        concept.noteRevision = dto.noteRevision
        concept.answerSourceJSON = encodeAnswerSource(dto.answerSource)
        concept.updatedAt = .now

        if existingConcept == nil {
            modelContext.insert(concept)
        }

        let note = concept.note ?? ConceptNote(concept: concept)
        let existingNoteRevision = note.revision
        note.revision = dto.noteRevision
        note.updatedAt = .now
        note.updatedBy = "backend"
        concept.note = note

        let shouldKeepExistingBlocks = existingConcept != nil
            && dto.noteRevision == existingNoteRevision
            && dto.blocks.isEmpty
            && !note.blocks.isEmpty
        if !shouldKeepExistingBlocks {
            let existingBlocks = note.blocks
            let existingById = Dictionary(uniqueKeysWithValues: existingBlocks.map { ($0.id, $0) })
            let reconciled = dto.blocks.map { blockDTO in
                if let block = existingById[blockDTO.id] {
                    block.blockType = blockDTO.blockType
                    block.content = blockDTO.content
                    block.source = blockDTO.source
                    block.isUserLocked = blockDTO.isUserLocked
                    block.lastEditedBy = blockDTO.source
                    block.position = blockDTO.position
                    block.updatedAt = .now
                    block.note = note
                    return block
                }
                let block = NoteBlock(
                    id: blockDTO.id,
                    blockType: blockDTO.blockType,
                    content: blockDTO.content,
                    source: blockDTO.source,
                    isUserLocked: blockDTO.isUserLocked,
                    lastEditedBy: blockDTO.source,
                    position: blockDTO.position,
                    note: note
                )
                modelContext.insert(block)
                return block
            }
            let remoteIds = Set(dto.blocks.map(\.id))
            note.blocks = reconciled
            for staleBlock in existingBlocks where !remoteIds.contains(staleBlock.id) {
                modelContext.delete(staleBlock)
            }
        }

        try replaceConceptTags(conceptId: concept.id, names: dto.tags)
        try replaceConceptTopics(conceptId: concept.id, names: dto.topics)
        try replaceConceptRelations(conceptId: concept.id, relations: dto.relations)

        return concept
    }

    func upsertConcepts(from dtos: [ConceptDTO]) throws {
        for dto in dtos {
            _ = try upsertConcept(from: dto)
        }
    }

    func pruneLocalMirrorsMissingFromRemote(keeping remoteIds: Set<UUID>) throws {
        let concepts = try modelContext.fetch(FetchDescriptor<Concept>())
        let localOnlyMirrors = concepts.filter { concept in
            !remoteIds.contains(concept.id)
                && !ConceptStatusRules.isLocalOnly(concept.captureStatus)
        }
        for concept in localOnlyMirrors {
            modelContext.delete(concept)
        }
    }

    func deleteConcept(_ concept: Concept) {
        modelContext.delete(concept)
    }

    func archiveConcept(_ concept: Concept) {
        concept.captureStatus = CaptureStatus.archived.rawValue
        concept.updatedAt = .now
    }

    func updateConceptSummary(
        _ concept: Concept,
        displayTitle: String,
        oneLineExplanation: String
    ) throws {
        let title = displayTitle.trimmingCharacters(in: .whitespacesAndNewlines)
        concept.displayTitle = title.isEmpty ? concept.displayTitle : title
        concept.canonicalTitle = title.isEmpty ? concept.canonicalTitle : title
        concept.oneLineExplanation = oneLineExplanation.trimmingCharacters(in: .whitespacesAndNewlines)
        concept.updatedAt = .now
        try recordManualEdit(for: concept)
    }

    func updateNoteBlock(_ block: NoteBlock, content: String) throws {
        guard let note = block.note, let concept = note.concept else { return }
        block.content = content.trimmingCharacters(in: .whitespacesAndNewlines)
        block.source = NoteBlockSource.user.rawValue
        block.isUserLocked = true
        block.lastEditedBy = UpdateActor.user.rawValue
        block.updatedAt = .now
        try recordManualEdit(for: concept)
    }

    func replaceConceptTags(conceptId: UUID, names: [String]) throws {
        let existingAssignments = try modelContext.fetch(FetchDescriptor<ConceptTag>())
            .filter { $0.conceptId == conceptId }
        for assignment in existingAssignments {
            modelContext.delete(assignment)
        }

        for name in normalizedNames(names) {
            let tag = try findOrCreateTag(named: name)
            modelContext.insert(ConceptTag(conceptId: conceptId, tagId: tag.id, source: UpdateActor.user.rawValue))
        }
    }

    /// Replace this concept's **backend-managed (card) topic** assignments with
    /// `names`. Local Library category assignments (`source == "category"`) are
    /// never touched — remote refresh / full-note save can't delete them.
    /// See `LibraryCategoryOwnership` and docs/architecture/local-library-category-boundary.md.
    func replaceConceptTopics(conceptId: UUID, names: [String]) throws {
        let cardAssignments = try modelContext.fetch(FetchDescriptor<ConceptTopic>())
            .filter { $0.conceptId == conceptId && !LibraryCategoryOwnership.isCategory($0) }
        for assignment in cardAssignments {
            modelContext.delete(assignment)
        }

        for name in normalizedNames(names) {
            let topic = try findOrCreateTopic(named: name)
            modelContext.insert(ConceptTopic(conceptId: conceptId, topicId: topic.id, source: UpdateActor.user.rawValue))
        }
    }

    func addRelation(
        sourceConceptId: UUID,
        targetConceptId: UUID,
        relationType: String = "related"
    ) throws {
        guard sourceConceptId != targetConceptId else { return }
        let existingRelations = try modelContext.fetch(FetchDescriptor<ConceptRelation>())
        if existingRelations.contains(where: { relation in
            relation.sourceConceptId == sourceConceptId
                && relation.targetConceptId == targetConceptId
                && relation.relationType == relationType
        }) {
            return
        }
        modelContext.insert(
            ConceptRelation(
                sourceConceptId: sourceConceptId,
                targetConceptId: targetConceptId,
                relationType: relationType,
                status: "accepted",
                confidence: 1,
                source: UpdateActor.user.rawValue
            )
        )
    }

    func replaceConceptRelations(conceptId: UUID, relations: [ConceptRelationDTO]) throws {
        let existingRelations = try modelContext.fetch(FetchDescriptor<ConceptRelation>())
            .filter { relation in
                relation.sourceConceptId == conceptId || relation.targetConceptId == conceptId
            }
        for relation in existingRelations {
            modelContext.delete(relation)
        }

        for dto in relations {
            modelContext.insert(
                ConceptRelation(
                    id: dto.id,
                    sourceConceptId: dto.sourceConceptId,
                    targetConceptId: dto.targetConceptId,
                    relationType: dto.relationType,
                    status: dto.status,
                    confidence: dto.confidence,
                    source: dto.source
                )
            )
        }
    }

    func removeRelation(_ relation: ConceptRelation) {
        modelContext.delete(relation)
    }

    func recordFailedFollowUpDraft(concept: Concept, question: String) {
        let trimmedQuestion = question.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedQuestion.isEmpty else { return }
        let conversation = ensureConversation(for: concept)
        conversation.updatedAt = .now
        if conversation.messages.contains(where: { message in
            message.role == ConversationRole.user.rawValue
                && message.content == trimmedQuestion
                && message.updateMode == failedFollowUpUpdateMode
        }) {
            return
        }
        modelContext.insert(
            ConversationMessage(
                role: ConversationRole.user.rawValue,
                content: trimmedQuestion,
                createdAt: .now,
                updateMode: failedFollowUpUpdateMode,
                conversation: conversation
            )
        )
    }

    func latestFailedFollowUpDraft(for concept: Concept) -> String? {
        let conversation = ensureConversation(for: concept)
        return conversation.messages
            .filter { message in
                message.role == ConversationRole.user.rawValue
                    && message.updateMode == failedFollowUpUpdateMode
            }
            .sorted { $0.createdAt > $1.createdAt }
            .first?
            .content
    }

    func clearFailedFollowUpDrafts(for concept: Concept, matching question: String? = nil) {
        let conversation = ensureConversation(for: concept)
        let trimmedQuestion = question?.trimmingCharacters(in: .whitespacesAndNewlines)
        let drafts = conversation.messages.filter { message in
            message.role == ConversationRole.user.rawValue
                && message.updateMode == failedFollowUpUpdateMode
                && (trimmedQuestion == nil || message.content == trimmedQuestion)
        }
        for draft in drafts {
            modelContext.delete(draft)
        }
    }

    func upsertProposal(_ dto: UpdateProposalDTO, conceptId: UUID) throws -> ConceptUpdateProposal {
        let existingProposal = try fetchProposal(id: dto.id)
        let proposal = existingProposal ?? ConceptUpdateProposal(
            id: dto.id,
            conceptId: conceptId,
            sourceMessageId: UUID(),
            baseNoteRevision: dto.baseNoteRevision,
            patchOperationsJSON: "[]",
            rationale: dto.rationale,
            confidence: dto.confidence,
            status: dto.status
        )

        proposal.conceptId = conceptId
        proposal.baseNoteRevision = dto.baseNoteRevision
        proposal.patchOperationsJSON = try encodePatchOperations(dto.patchOperations)
        proposal.rationale = dto.rationale
        proposal.confidence = dto.confidence
        proposal.status = dto.status
        if dto.status != ProposalStatus.proposed.rawValue {
            proposal.resolvedAt = .now
        }

        if existingProposal == nil {
            modelContext.insert(proposal)
        }

        return proposal
    }

    func mergeIdempotencyKey(for proposal: ConceptUpdateProposal) -> UUID {
        if let existing = proposal.mergeIdempotencyKey,
           let uuid = UUID(uuidString: existing),
           proposal.mergeOperationStatus != LocalOperationStatus.failed.rawValue,
           proposal.mergeOperationStatus != LocalOperationStatus.completed.rawValue {
            proposal.mergeOperationStatus = LocalOperationStatus.inFlight.rawValue
            return uuid
        }
        let key = UUID()
        proposal.mergeIdempotencyKey = key.uuidString
        proposal.mergeOperationStatus = LocalOperationStatus.inFlight.rawValue
        return key
    }

    func markProposalMergeCompleted(_ proposal: ConceptUpdateProposal) {
        proposal.mergeOperationStatus = LocalOperationStatus.completed.rawValue
        proposal.mergeIdempotencyKey = nil
        proposal.resolvedAt = .now
    }

    func markProposalMergeFailed(_ proposal: ConceptUpdateProposal) {
        proposal.mergeOperationStatus = LocalOperationStatus.failed.rawValue
    }

    func markProposal(id: UUID, status: ProposalStatus) throws {
        guard let proposal = try fetchProposal(id: id) else { return }
        proposal.status = status.rawValue
        proposal.resolvedAt = .now
    }

    private func fetchConcept(id: UUID) throws -> Concept? {
        var descriptor = FetchDescriptor<Concept>(
            predicate: #Predicate<Concept> { concept in
                concept.id == id
            }
        )
        descriptor.fetchLimit = 1
        return try modelContext.fetch(descriptor).first
    }

    private func fetchProposal(id: UUID) throws -> ConceptUpdateProposal? {
        var descriptor = FetchDescriptor<ConceptUpdateProposal>(
            predicate: #Predicate<ConceptUpdateProposal> { proposal in
                proposal.id == id
            }
        )
        descriptor.fetchLimit = 1
        return try modelContext.fetch(descriptor).first
    }

    private func encodePatchOperations(_ operations: [PatchOperationDTO]) throws -> String {
        let data = try JSONEncoder().encode(operations)
        return String(data: data, encoding: .utf8) ?? "[]"
    }

    private func encodeAnswerSource(_ answerSource: AnswerSourceDTO?) -> String? {
        guard let answerSource,
              let data = try? JSONEncoder().encode(answerSource) else {
            return nil
        }
        return String(data: data, encoding: .utf8)
    }

    private func ensureConversation(for concept: Concept) -> Conversation {
        if let conversation = concept.conversation {
            return conversation
        }
        let conversation = Conversation(
            initialQuery: concept.displayTitle,
            concept: concept
        )
        concept.conversation = conversation
        modelContext.insert(conversation)
        return conversation
    }

    private func recordManualEdit(for concept: Concept) throws {
        let nextRevision = concept.noteRevision + 1
        concept.noteRevision = nextRevision
        concept.updatedAt = .now
        if let note = concept.note {
            note.revision = nextRevision
            note.updatedAt = .now
            note.updatedBy = UpdateActor.user.rawValue
        }

        modelContext.insert(
            NoteRevision(
                conceptId: concept.id,
                revision: nextRevision,
                snapshotJSON: snapshotJSON(for: concept),
                mergeMode: UpdateEventType.manualEdit.rawValue
            )
        )
        modelContext.insert(
            UpdateEvent(
                conceptId: concept.id,
                noteRevision: nextRevision,
                eventType: UpdateEventType.manualEdit.rawValue,
                actor: UpdateActor.user.rawValue
            )
        )
    }

    private func snapshotJSON(for concept: Concept) -> String {
        let blocks = (concept.note?.blocks ?? []).map { block in
            [
                "id": block.id.uuidString,
                "blockType": block.blockType,
                "content": block.content,
                "source": block.source,
                "isUserLocked": block.isUserLocked ? "true" : "false"
            ]
        }
        let snapshot: [String: Any] = [
            "conceptId": concept.id.uuidString,
            "displayTitle": concept.displayTitle,
            "oneLineExplanation": concept.oneLineExplanation,
            "noteRevision": concept.noteRevision,
            "blocks": blocks
        ]
        guard JSONSerialization.isValidJSONObject(snapshot),
              let data = try? JSONSerialization.data(withJSONObject: snapshot),
              let json = String(data: data, encoding: .utf8) else {
            return "{}"
        }
        return json
    }

    private func normalizedNames(_ names: [String]) -> [String] {
        var seen = Set<String>()
        return names.compactMap { rawName in
            let name = rawName.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !name.isEmpty else { return nil }
            let key = name.lowercased()
            guard !seen.contains(key) else { return nil }
            seen.insert(key)
            return name
        }
    }

    private func findOrCreateTag(named name: String) throws -> Tag {
        let tags = try modelContext.fetch(FetchDescriptor<Tag>())
        if let existing = tags.first(where: { $0.name.localizedCaseInsensitiveCompare(name) == .orderedSame }) {
            return existing
        }
        let tag = Tag(name: name, source: UpdateActor.user.rawValue)
        modelContext.insert(tag)
        return tag
    }

    /// Find or create a **card-metadata** Topic. Local Library category Topics
    /// (`source == "category"`) are excluded from lookup, so a card topic never
    /// reuses a category `Topic` even when they share a name (no source pollution).
    private func findOrCreateTopic(named name: String) throws -> Topic {
        let topics = try modelContext.fetch(FetchDescriptor<Topic>())
        if let existing = topics.first(where: {
            !LibraryCategoryOwnership.isCategory($0)
                && $0.name.localizedCaseInsensitiveCompare(name) == .orderedSame
        }) {
            return existing
        }
        let topic = Topic(name: name, source: UpdateActor.user.rawValue)
        modelContext.insert(topic)
        return topic
    }

    private func lookupKeys(for concept: Concept) -> Set<String> {
        let aliases = concept.aliasesText.split { character in
            character == "," || character == "\n" || character == "，"
        }
        return Set(
            ([concept.canonicalTitle, concept.displayTitle] + aliases.map(String.init))
                .map(normalizedLookupKey)
                .filter { !$0.isEmpty }
        )
    }

    private func normalizedLookupKey(_ value: String) -> String {
        value
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
            .replacingOccurrences(of: #"\s+"#, with: " ", options: .regularExpression)
    }

    private var failedFollowUpUpdateMode: String {
        LocalConversationMarker.failed
    }

    private var initialCaptureUpdateMode: String {
        LocalConversationMarker.initialCapture
    }
}

enum CaptureMatchResult {
    case none
    case exact(Concept)
    case ambiguous([Concept])
}
