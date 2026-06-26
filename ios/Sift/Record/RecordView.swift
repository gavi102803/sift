import SwiftData
import SwiftUI

struct RecordView: View {
    @Environment(\.appServices) private var appServices
    @Environment(\.modelContext) private var modelContext
    var onSearch: () -> Void = {}
    var onOpenConcept: (UUID, ConceptDetailMode) -> Void = { _, _ in }
    var onReplaceOpenedConcept: (UUID, UUID) -> Void = { _, _ in }
    @State private var captureText = ""
    @State private var errorMessage: String?
    @State private var isSubmitting = false
    @StateObject private var speechCapture = SpeechCaptureService()

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 28) {
                brandHeader
                captureHero
                if let errorMessage {
                    InlineErrorView(message: errorMessage) {
                        Task {
                            await refreshConcepts()
                        }
                    }
                }
            }
            .padding(20)
            .padding(.bottom, 92)
        }
        .scrollContentBackground(.hidden)
        .siftScreenBackground()
        .navigationTitle("")
        .navigationBarTitleDisplayMode(.inline)
        .refreshable {
            await refreshConcepts()
        }
        .task {
            await refreshConcepts()
        }
        .safeAreaInset(edge: .bottom) {
            captureComposer
        }
    }

    private var brandHeader: some View {
        HStack {
            SiftLogo(symbolSize: 54)
            Spacer()
        }
        .padding(.top, 8)
    }

    private var captureHero: some View {
        VStack(spacing: 18) {
            Spacer(minLength: 0)
            SiftSymbol(size: 82)

            VStack(spacing: 8) {
                Text("What new concept did you hear?")
                    .font(.title2.weight(.semibold))
                    .multilineTextAlignment(.center)
                Text("Capture it now.\nDeepen it later.")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
                    .lineSpacing(3)
            }
            Spacer(minLength: 0)
        }
        .frame(maxWidth: .infinity)
        .frame(minHeight: 500)
    }

    private var captureComposer: some View {
        HStack(spacing: 10) {
            Image(systemName: "plus")
                .foregroundStyle(.secondary)

            TextField("Capture a concept", text: $captureText, axis: .vertical)
                .textFieldStyle(.plain)
                .lineLimit(1...3)

            Button {
                Task {
                    await toggleSpeechCapture()
                }
            } label: {
                Image(systemName: speechCapture.isRecording ? "mic.fill" : "mic")
                    .frame(width: 30, height: 30)
            }
            .buttonStyle(.plain)
            .foregroundStyle(speechCapture.isRecording ? .red : .secondary)
            .disabled(isSubmitting)
            .accessibilityLabel(
                speechCapture.isRecording ? "Stop voice input" : "Start voice input"
            )

            Button {
                Task {
                    await captureConcept()
                }
            } label: {
                if isSubmitting {
                    ProgressView()
                        .frame(width: 34, height: 34)
                } else {
                    Image(systemName: "arrow.right")
                        .font(.headline)
                        .frame(width: 34, height: 34)
                }
            }
            .buttonStyle(.borderedProminent)
            .buttonBorderShape(.circle)
            .disabled(
                isSubmitting
                    || captureText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            )
            .accessibilityLabel("Capture concept")
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
        .background(.ultraThinMaterial, in: Capsule())
        .overlay {
            Capsule().stroke(SiftTheme.border, lineWidth: 1)
        }
        .shadow(color: Color.black.opacity(0.08), radius: 18, y: 8)
        .padding(.horizontal, 20)
        .padding(.bottom, 8)
    }

    private func captureConcept() async {
        let service = CaptureFlowService(
            localStore: ConceptLocalStore(modelContext: modelContext),
            apiClient: appServices.apiClient
        )
        let draft: Concept

        isSubmitting = true
        errorMessage = nil
        do {
            switch try service.resolveCapture(rawCapture: captureText) {
            case .empty:
                isSubmitting = false
                return
            case .existing(let concept):
                captureText = ""
                onOpenConcept(concept.id, .followUp)
                isSubmitting = false
                return
            case .needsDisambiguation(_, let matches):
                errorMessage = "Possible matches found: \(matches.prefix(3).map(\.displayTitle).joined(separator: ", ")). Review this saved draft before generating."
                captureText = ""
                isSubmitting = false
                return
            case .newDraft(let newDraft):
                draft = newDraft
            }
        } catch {
            errorMessage = error.localizedDescription
            isSubmitting = false
            return
        }

        captureText = ""
        onOpenConcept(draft.id, .followUp)
        isSubmitting = false
        do {
            let generated = try await service.generateConcept(from: draft)
            onReplaceOpenedConcept(draft.id, generated.id)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func toggleSpeechCapture() async {
        if speechCapture.isRecording {
            speechCapture.stop()
            return
        }

        do {
            try await speechCapture.start { transcript in
                captureText = transcript
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func refreshConcepts() async {
        do {
            let concepts = try await appServices.apiClient.listConcepts()
            let store = ConceptLocalStore(modelContext: modelContext)
            try store.upsertConcepts(from: concepts)
            try store.pruneLocalMirrorsMissingFromRemote(keeping: Set(concepts.map(\.id)))
            errorMessage = nil
        } catch is CancellationError {
            return
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

#Preview {
    NavigationStack {
        RecordView()
    }
    .environment(\.appServices, .preview)
}
