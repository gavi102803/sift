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

    private func fetchConcept(id: UUID) throws -> Concept? {
        var descriptor = FetchDescriptor<Concept>(
            predicate: #Predicate<Concept> { concept in
                concept.id == id
            }
        )
        descriptor.fetchLimit = 1
        return try modelContext.fetch(descriptor).first
    }
}
