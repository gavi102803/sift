import SwiftUI

/// Default reading mode: a quiet, editorial knowledge card. Understanding leads;
/// system metadata is demoted to a collapsed Details section at the very bottom.
struct ConceptReadingView: View {
    var concept: Concept
    var tagNames: [String]
    var topicNames: [String]
    var relationRows: [RelatedConceptRowModel]
    var relatedCandidates: [Concept]
    /// Backend-written related-concepts prose, shown only when no real relations exist.
    var relatedDisplayFallback: String?
    var addRelationDisabled: Bool
    var removeRelationDisabled: Bool
    var isRetryingGeneration: Bool = false
    var onAddRelation: (Concept) -> Void
    var onRemoveRelation: (ConceptRelation) -> Void
    var onEditBlock: (NoteBlock) -> Void
    var onRetryGeneration: () -> Void = {}

    private var contentBlocks: [NoteBlock] {
        ReadingContent.orderedBlocks(concept.note?.blocks ?? [])
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 28) {
            title
            if !concept.oneLineExplanation.isEmpty {
                lede
            }
            ForEach(contentBlocks) { block in
                contentSection(block)
            }
            if contentBlocks.isEmpty {
                emptyContent
            }
            relatedSection
            detailsSection
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    // MARK: Title + lede

    private var title: some View {
        Text(concept.displayTitle)
            .font(SiftFont.pageTitle)
            .tracking(-0.6)
            .foregroundStyle(SiftColor.textPrimary)
            .lineLimit(4)
            .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var lede: some View {
        HStack(alignment: .top, spacing: 12) {
            RoundedRectangle(cornerRadius: 1, style: .continuous)
                .fill(SiftColor.accent)
                .frame(width: 2)
            Text(concept.oneLineExplanation)
                .font(SiftFont.sans(18))
                .foregroundStyle(SiftColor.textSecondary)
                .lineSpacing(5)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .fixedSize(horizontal: false, vertical: true)
    }

    // MARK: Content sections

    private func contentSection(_ block: NoteBlock) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(noteBlockTitle(block.blockType).uppercased())
                .font(SiftFont.eyebrow)
                .tracking(0.7)
                .foregroundStyle(SiftColor.textFaint)
            MarkdownText(CitationMarkup.removingMarkers(from: block.content))
                .foregroundStyle(SiftColor.textBody)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .contentShape(Rectangle())
        .contextMenu {
            Button {
                onEditBlock(block)
            } label: {
                Label("Edit", systemImage: "pencil")
            }
        }
    }

    private var emptyContent: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(emptyContentText)
                .font(SiftFont.body)
                .foregroundStyle(SiftColor.textMuted)
            if CaptureStatus(rawValue: concept.captureStatus) == .generationFailed {
                Button(action: onRetryGeneration) {
                    HStack(spacing: 6) {
                        if isRetryingGeneration {
                            ProgressView().controlSize(.small)
                        } else {
                            Image(systemName: "arrow.clockwise")
                                .font(.system(size: 12, weight: .semibold))
                            Text("Try again")
                                .font(SiftFont.sans(13, .semibold))
                        }
                    }
                    .foregroundStyle(SiftColor.accent)
                }
                .buttonStyle(.plain)
                .disabled(isRetryingGeneration)
                .accessibilityIdentifier("concept.generation.retry")
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var emptyContentText: String {
        switch CaptureStatus(rawValue: concept.captureStatus) {
        case .draft, .pendingGeneration, .generating, .buildingCard:
            return "Sift is preparing the first card. You can stay here while it works."
        case .generationFailed:
            return "Generation didn’t finish. Your original question is still here."
        default:
            return "This card is empty. Ask a follow-up to start growing it."
        }
    }

    // MARK: Related concepts (after the content)

    private var relatedSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("Related concepts".uppercased())
                    .font(SiftFont.eyebrow)
                    .tracking(0.7)
                    .foregroundStyle(SiftColor.textFaint)
                Spacer()
                Menu {
                    if relatedCandidates.isEmpty {
                        Text("No concepts available")
                    } else {
                        ForEach(relatedCandidates) { candidate in
                            Button(candidate.displayTitle) {
                                onAddRelation(candidate)
                            }
                        }
                    }
                } label: {
                    Image(systemName: "plus")
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundStyle(SiftColor.textMuted)
                        .frame(width: 28, height: 28)
                }
                .accessibilityLabel("Add related concept")
                .disabled(addRelationDisabled)
            }

            if !relationRows.isEmpty {
                ForEach(relationRows) { row in
                    RelatedConceptRow(row: row) {
                        onRemoveRelation(row.relation)
                    }
                    .disabled(removeRelationDisabled)
                }
            } else if let relatedDisplayFallback, !relatedDisplayFallback.isEmpty {
                MarkdownText(relatedDisplayFallback)
                    .foregroundStyle(SiftColor.textMuted)
                    .frame(maxWidth: .infinity, alignment: .leading)
            } else {
                Text("No related concepts yet")
                    .font(SiftFont.cardDesc)
                    .foregroundStyle(SiftColor.textFaint)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
    }

    // MARK: Details (demoted metadata)

    private var detailsSection: some View {
        DisclosureGroup {
            VStack(spacing: 0) {
                detailRow("Maturity", value: concept.maturity.capitalized)
                SiftGroupDivider()
                detailRow("Status", value: statusLabel(concept.captureStatus))
                if !topicNames.isEmpty {
                    SiftGroupDivider()
                    detailRow("Topics", value: topicNames.joined(separator: ", "))
                }
                if !tagNames.isEmpty {
                    SiftGroupDivider()
                    detailRow("Tags", value: tagNames.joined(separator: ", "))
                }
            }
            .padding(.top, 10)
        } label: {
            Text("Details")
                .font(SiftFont.sans(13, .medium))
                .foregroundStyle(SiftColor.textMuted)
        }
        .tint(SiftColor.textMuted)
        .padding(.top, 4)
    }

    private func detailRow(_ label: String, value: String) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Text(label)
                .font(SiftFont.cardDesc)
                .foregroundStyle(SiftColor.textFaint)
                .frame(width: 78, alignment: .leading)
            Text(value)
                .font(SiftFont.cardDesc)
                .foregroundStyle(SiftColor.textBody)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(.vertical, 9)
    }

    private func statusLabel(_ status: String) -> String {
        switch CaptureStatus(rawValue: status) {
        case .ready: "Ready"
        case .generating, .pendingGeneration, .buildingCard, .draft: "Generating"
        case .generationFailed: "Failed"
        case .needsDisambiguation: "Review"
        case .archived: "Archived"
        case .none: status
        }
    }
}

// MARK: - Related concept row

struct RelatedConceptRowModel: Identifiable {
    var relation: ConceptRelation
    var concept: Concept
    var id: UUID { relation.id }
}

struct RelatedConceptRow: View {
    var row: RelatedConceptRowModel
    var onRemove: () -> Void

    var body: some View {
        HStack(spacing: 12) {
            NavigationLink(value: row.concept.id) {
                VStack(alignment: .leading, spacing: 3) {
                    Text(row.concept.displayTitle)
                        .font(SiftFont.sans(15, .medium))
                        .foregroundStyle(SiftColor.textPrimary)
                    Text(row.relation.relationType)
                        .font(SiftFont.cardDesc)
                        .foregroundStyle(SiftColor.textFaint)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .buttonStyle(.plain)

            Button(action: onRemove) {
                Image(systemName: "xmark")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(SiftColor.textFaint)
                    .frame(width: 28, height: 28)
            }
            .buttonStyle(.borderless)
            .accessibilityLabel("Remove related concept")
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 12)
        .background(SiftColor.surface, in: RoundedRectangle(cornerRadius: SiftRadius.tile, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: SiftRadius.tile, style: .continuous)
                .strokeBorder(SiftColor.hairline, lineWidth: 1)
        )
    }
}
