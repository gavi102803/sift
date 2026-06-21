import SwiftData
import SwiftUI

struct RecordView: View {
    @Environment(\.modelContext) private var modelContext
    @Query(sort: \Concept.updatedAt, order: .reverse) private var recentConcepts: [Concept]
    @State private var captureText = ""
    @State private var errorMessage: String?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                captureCard
                if let errorMessage {
                    Text(errorMessage)
                        .font(.footnote)
                        .foregroundStyle(.red)
                }
                recentSection
            }
            .padding(20)
        }
        .navigationTitle("Sift")
        .toolbar {
            Button {
                // Search will be wired once the library query flow is in place.
            } label: {
                Image(systemName: "magnifyingglass")
            }
            .accessibilityLabel("Search concepts")
        }
    }

    private var captureCard: some View {
        VStack(spacing: 20) {
            VStack(spacing: 8) {
                Text("What new concept did you hear?")
                    .font(.title3.weight(.semibold))
                Text("Capture it first. Sift can deepen it later.")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }

            TextField("Type a concept or phrase", text: $captureText, axis: .vertical)
                .textFieldStyle(.plain)
                .lineLimit(2...5)
                .padding(14)
                .background(.quaternary.opacity(0.35), in: RoundedRectangle(cornerRadius: 8))

            HStack {
                Button {
                    // Voice input is deferred until the text capture path is stable.
                } label: {
                    Image(systemName: "mic")
                        .frame(width: 36, height: 36)
                }
                .buttonStyle(.bordered)
                .accessibilityLabel("Voice input")

                Spacer()

                Button(action: saveDraft) {
                    Image(systemName: "arrow.right")
                        .frame(width: 42, height: 36)
                }
                .buttonStyle(.borderedProminent)
                .disabled(captureText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                .accessibilityLabel("Save concept draft")
            }
        }
        .padding(18)
        .background(.background, in: RoundedRectangle(cornerRadius: 8))
        .overlay {
            RoundedRectangle(cornerRadius: 8)
                .stroke(.quaternary, lineWidth: 1)
        }
    }

    private var recentSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Recent")
                .font(.headline)

            if recentConcepts.isEmpty {
                ContentUnavailableView(
                    "No concepts yet",
                    systemImage: "rectangle.stack.badge.plus",
                    description: Text("Saved drafts will appear here.")
                )
            } else {
                ForEach(recentConcepts.prefix(5)) { concept in
                    NavigationLink(value: concept.id) {
                        ConceptRow(concept: concept)
                    }
                    .buttonStyle(.plain)
                }
            }
        }
        .navigationDestination(for: UUID.self) { conceptId in
            ConceptDetailView(conceptId: conceptId)
        }
    }

    private func saveDraft() {
        let service = CaptureFlowService(
            localStore: ConceptLocalStore(modelContext: modelContext),
            apiClient: MockSiftAPIClient()
        )
        guard service.saveDraft(rawCapture: captureText) != nil else { return }
        captureText = ""
        errorMessage = nil
    }
}

private struct ConceptRow: View {
    var concept: Concept

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(concept.displayTitle)
                .font(.body.weight(.medium))
                .foregroundStyle(.primary)
            Text(concept.oneLineExplanation.isEmpty ? concept.captureStatus : concept.oneLineExplanation)
                .font(.footnote)
                .foregroundStyle(.secondary)
                .lineLimit(2)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(.background, in: RoundedRectangle(cornerRadius: 8))
        .overlay {
            RoundedRectangle(cornerRadius: 8)
                .stroke(.quaternary, lineWidth: 1)
        }
    }
}

#Preview {
    NavigationStack {
        RecordView()
    }
}
