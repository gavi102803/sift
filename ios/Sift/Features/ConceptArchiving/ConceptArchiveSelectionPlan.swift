import Foundation

struct ConceptArchiveSelectionPlan {
    let remoteConceptIds: [UUID]
    let localDraftIds: [UUID]

    init(concepts: [Concept], backendConceptIds: Set<UUID> = []) {
        remoteConceptIds = concepts
            .filter {
                backendConceptIds.contains($0.id)
                    || !ConceptStatusRules.isLocalOnly($0.captureStatus)
            }
            .map(\.id)
        localDraftIds = concepts
            .filter {
                !backendConceptIds.contains($0.id)
                    && ConceptStatusRules.isLocalOnly($0.captureStatus)
            }
            .map(\.id)
    }

    static func requiresBackendRefresh(
        concepts: [Concept],
        backendConceptIds _: Set<UUID>
    ) -> Bool {
        concepts.contains {
            $0.captureStatus == CaptureStatus.generationFailed.rawValue
        }
    }

    var totalCount: Int {
        remoteConceptIds.count + localDraftIds.count
    }

    var confirmationTitle: String {
        if remoteConceptIds.isEmpty {
            return "Discard \(itemCount(localDraftIds.count, singular: "unfinished draft"))?"
        }
        if localDraftIds.isEmpty {
            return "Move \(itemCount(remoteConceptIds.count, singular: "card")) to Recently Deleted?"
        }
        return "Delete \(itemCount(totalCount, singular: "selected item"))?"
    }

    var confirmationActionTitle: String {
        if remoteConceptIds.isEmpty {
            return localDraftIds.count == 1 ? "Discard Draft" : "Discard Drafts"
        }
        if localDraftIds.isEmpty {
            return "Move to Recently Deleted"
        }
        return "Move Cards and Discard Drafts"
    }

    var confirmationMessage: String {
        if remoteConceptIds.isEmpty {
            return "These unfinished drafts were never saved to the Backend and cannot be restored."
        }
        if localDraftIds.isEmpty {
            return "You can restore these cards later."
        }
        return "\(itemCount(remoteConceptIds.count, singular: "card")) can be restored later. "
            + "\(itemCount(localDraftIds.count, singular: "unfinished draft")) will be permanently discarded."
    }

    private func itemCount(_ count: Int, singular: String) -> String {
        "\(count) \(singular)\(count == 1 ? "" : "s")"
    }
}
