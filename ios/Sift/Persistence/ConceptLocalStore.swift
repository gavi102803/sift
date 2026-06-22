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
        concept.updatedAt = .now

        if existingConcept == nil {
            modelContext.insert(concept)
        }

        let note = concept.note ?? ConceptNote(concept: concept)
        note.revision = dto.noteRevision
        note.updatedAt = .now
        note.updatedBy = "backend"
        concept.note = note

        note.blocks.removeAll()
        note.blocks = dto.blocks.map { blockDTO in
            NoteBlock(
                id: blockDTO.id,
                blockType: blockDTO.blockType,
                content: blockDTO.content,
                source: blockDTO.source,
                isUserLocked: blockDTO.isUserLocked,
                lastEditedBy: blockDTO.source,
                note: note
            )
        }

        return concept
    }

    func upsertConcepts(from dtos: [ConceptDTO]) throws {
        for dto in dtos {
            _ = try upsertConcept(from: dto)
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
}
