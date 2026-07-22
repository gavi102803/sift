import SwiftData
import SwiftUI

struct ConceptHistoryView: View {
    @Environment(\.appServices) private var appServices
    @Environment(\.modelContext) private var modelContext
    @Environment(\.dismiss) private var dismiss
    @Environment(CompanionMonitor.self) private var companion: CompanionMonitor?

    let conceptId: UUID
    var onRestored: (ConceptDTO) -> Void

    @State private var revisions: [NoteRevisionSummaryDTO] = []
    @State private var selectedRevision: NoteRevisionDTO?
    @State private var restoringRevision: NoteRevisionDTO?
    @State private var isLoading = true
    @State private var isRestoring = false
    @State private var errorMessage: String?
    @State private var backendReachable = false
    @State private var restoreAvailabilityChecked = false

    private var canRestore: Bool {
        backendReachable
            && restoreAvailabilityChecked
            && companion?.status != .unavailable
    }

    var body: some View {
        NavigationStack {
            Group {
                if isLoading {
                    ProgressView()
                } else if revisions.isEmpty {
                    ContentUnavailableView(
                        "No version history",
                        systemImage: "clock.arrow.circlepath",
                        description: Text(errorMessage ?? "Versions appear after the card is saved.")
                    )
                } else {
                    List(revisions) { revision in
                        Button {
                            Task { await loadRevision(revision.revision) }
                        } label: {
                            HStack {
                                VStack(alignment: .leading, spacing: 4) {
                                    Text("Version \(revision.revision)")
                                        .font(.headline)
                                    Text(revisionSource(revision.source))
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                    Text(revision.createdAt, format: .dateTime.year().month().day().hour().minute())
                                        .font(.caption2)
                                        .foregroundStyle(.tertiary)
                                }
                                Spacer()
                                if revision.isCurrent {
                                    Text("Current")
                                        .font(.caption.weight(.semibold))
                                        .foregroundStyle(SiftColor.accent)
                                }
                                Image(systemName: "chevron.right")
                                    .foregroundStyle(.tertiary)
                            }
                        }
                        .buttonStyle(.plain)
                        .accessibilityIdentifier("concept.history.revision.\(revision.revision)")
                    }
                }
            }
            .navigationTitle("Version history")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Done") { dismiss() }
                }
            }
            .navigationDestination(item: $selectedRevision) { revision in
                revisionPreview(revision)
            }
        }
        .task { await loadRevisions() }
        .alert("Restore this version?", isPresented: Binding(
            get: { restoringRevision != nil },
            set: { if !$0 { restoringRevision = nil } }
        )) {
            Button("Cancel", role: .cancel) { restoringRevision = nil }
            Button("Restore") {
                guard let revision = restoringRevision else { return }
                Task { await restore(revision) }
            }
        } message: {
            Text("Sift will create a new version. Conversation history and knowledge metadata stay unchanged.")
        }
    }

    private func revisionPreview(_ revision: NoteRevisionDTO) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                Text(revision.displayTitle).font(.title2.bold())
                if !revision.oneLineExplanation.isEmpty {
                    Text(revision.oneLineExplanation).foregroundStyle(.secondary)
                }
                ForEach(revision.blocks) { block in
                    VStack(alignment: .leading, spacing: 6) {
                        Text(block.blockType.siftHumanized).font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                        Text(block.content)
                    }
                }
                if let errorMessage {
                    Text(errorMessage).font(.footnote).foregroundStyle(.red)
                }
                if !canRestore {
                    Text("Connect to the backend to restore this version.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                        .accessibilityIdentifier("concept.history.offline")
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding()
        }
        .navigationTitle("Version \(revision.revision)")
        .task(id: revision.id) {
            await checkRestoreAvailability()
        }
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button(isRestoring ? "Restoring…" : "Restore") {
                    restoringRevision = revision
                }
                .disabled(revision.isCurrent || isRestoring || !canRestore)
                .accessibilityIdentifier("concept.history.restore")
            }
        }
    }

    private func loadRevisions() async {
        isLoading = true
        defer { isLoading = false }
        do {
            revisions = try await appServices.apiClient.listRevisions(conceptId: conceptId)
            backendReachable = true
            errorMessage = nil
        } catch is CancellationError {
            return
        } catch {
            backendReachable = false
            companion?.note(error)
            errorMessage = "Connect to the backend to browse and restore versions."
        }
    }

    private func loadRevision(_ revision: Int) async {
        restoreAvailabilityChecked = false
        do {
            selectedRevision = try await appServices.apiClient.getRevision(conceptId: conceptId, revision: revision)
            backendReachable = true
            errorMessage = nil
        } catch {
            backendReachable = false
            companion?.note(error)
            errorMessage = "This version could not be loaded."
        }
    }

    private func checkRestoreAvailability() async {
        do {
            _ = try await appServices.apiClient.getAppStatus()
            backendReachable = true
            restoreAvailabilityChecked = true
            companion?.noteSuccess()
        } catch is CancellationError {
            return
        } catch {
            backendReachable = false
            restoreAvailabilityChecked = true
            companion?.note(error)
        }
    }

    private func restore(_ revision: NoteRevisionDTO) async {
        restoringRevision = nil
        isRestoring = true
        defer { isRestoring = false }
        do {
            let concept = try await appServices.apiClient.restoreRevision(conceptId: conceptId, revision: revision.revision)
            backendReachable = true
            _ = try ConceptLocalStore(modelContext: modelContext).upsertConcept(from: concept)
            onRestored(concept)
            selectedRevision = nil
            await loadRevisions()
        } catch {
            backendReachable = false
            companion?.note(error)
            errorMessage = "Restore requires an online backend connection."
        }
    }

    private func revisionSource(_ source: String) -> String {
        switch source {
        case "revisionRestore": "Restored version"
        case "manualEdit": "Manual edit"
        case "confirmedMerge": "Confirmed update"
        case "initialGeneration": "Initial card"
        default: source.siftHumanized
        }
    }
}

private extension String {
    var siftHumanized: String {
        unicodeScalars.reduce(into: "") { result, scalar in
            if CharacterSet.uppercaseLetters.contains(scalar), !result.isEmpty { result.append(" ") }
            result.append(Character(scalar))
        }
        .replacingOccurrences(of: "_", with: " ")
        .capitalized
    }
}
