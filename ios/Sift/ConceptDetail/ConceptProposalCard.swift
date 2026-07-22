import SwiftUI

/// A quiet "Suggested update" card. Shows only natural-language copy — never
/// patch operations, revision ids, or internal policy names. Copy degrades
/// deterministically (see `ProposalCopy`).
struct SuggestedUpdateCard: View {
    var concept: Concept
    var proposal: ConceptUpdateProposal
    var isResolving: Bool
    var onConfirm: () -> Void
    var onKeep: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text(proposal.origin == "periodicReview" ? "Periodic review" : "Suggested update")
                .font(SiftFont.eyebrow)
                .tracking(0.6)
                .foregroundStyle(SiftColor.accentTextOnWash)

            Text(ProposalCopy.userFacingText(rationale: proposal.rationale, targetTitle: targetTitle))
                .font(SiftFont.body)
                .foregroundStyle(SiftColor.textSecondary)
                .lineSpacing(4)
                .frame(maxWidth: .infinity, alignment: .leading)

            HStack(spacing: 10) {
                Button(action: onConfirm) {
                    Group {
                        if isResolving {
                            ProgressView().tint(.white)
                        } else {
                            Text("Confirm update")
                                .font(SiftFont.sans(14, .semibold))
                                .foregroundStyle(.white)
                        }
                    }
                    .frame(maxWidth: .infinity)
                    .frame(height: 40)
                    .background(SiftColor.accent, in: RoundedRectangle(cornerRadius: SiftRadius.button, style: .continuous))
                }
                .buttonStyle(.plain)
                .disabled(isResolving)

                Button(action: onKeep) {
                    Text("Keep current")
                        .font(SiftFont.sans(14, .medium))
                        .foregroundStyle(SiftColor.textSecondary)
                        .frame(maxWidth: .infinity)
                        .frame(height: 40)
                        .background(SiftColor.surfaceSoft, in: RoundedRectangle(cornerRadius: SiftRadius.button, style: .continuous))
                        .overlay(
                            RoundedRectangle(cornerRadius: SiftRadius.button, style: .continuous)
                                .strokeBorder(SiftColor.hairline, lineWidth: 1)
                        )
                }
                .buttonStyle(.plain)
                .disabled(isResolving)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(16)
        .background(SiftColor.surface, in: RoundedRectangle(cornerRadius: SiftRadius.card, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: SiftRadius.card, style: .continuous)
                .strokeBorder(SiftColor.accentBorder, lineWidth: 1)
        )
        .siftCardShadow()
    }

    /// Human title of the block this update targets, if we can resolve one.
    /// Used only as a deterministic copy fallback — never shown as raw data.
    private var targetTitle: String? {
        guard let data = proposal.patchOperationsJSON.data(using: .utf8),
              let operations = try? JSONDecoder().decode([PatchOperationDTO].self, from: data) else {
            return nil
        }
        for operation in operations {
            if let targetBlockId = operation.targetBlockId,
               let block = concept.note?.blocks.first(where: { $0.id == targetBlockId }) {
                return noteBlockTitle(block.blockType)
            }
        }
        return nil
    }
}
