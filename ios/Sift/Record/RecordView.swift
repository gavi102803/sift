import SwiftData
import SwiftUI

struct RecordView: View {
    @Environment(\.appServices) private var appServices
    @Environment(\.modelContext) private var modelContext
    @Environment(CompanionMonitor.self) private var companion: CompanionMonitor?
    var onSearch: () -> Void = {}
    var onOpenConcept: (UUID, ConceptDetailMode) -> Void = { _, _ in }
    var onGenerateConcept: (Concept) -> Void = { _ in }
    @State private var captureText = ""
    @State private var errorMessage: String?
    @State private var isSubmitting = false
    @StateObject private var speechCapture = SpeechCaptureService()

    var body: some View {
        VStack(alignment: .leading, spacing: 24) {
            captureHero
            if let errorMessage {
                InlineErrorView(message: errorMessage) {
                    Task {
                        await refreshConcepts()
                    }
                }
            }
        }
        .padding(.horizontal, 24)
        .safeAreaInset(edge: .bottom) {
            captureComposer
        }
        .siftScreenBackground()
        .navigationBarHidden(true)
        .task {
            await refreshConcepts()
        }
    }

    private var captureHero: some View {
        VStack(spacing: 18) {
            Spacer(minLength: 0)
            SiftSymbol(size: 98)

            VStack(spacing: 10) {
                Text("What new concept did you hear?")
                    .font(SiftFont.hero)
                    .tracking(-0.5)
                    .foregroundStyle(SiftColor.textPrimary)
                    .multilineTextAlignment(.center)
                    .lineSpacing(7)
                Text("Capture it now. Deepen it later.")
                    .font(SiftFont.body)
                    .foregroundStyle(SiftColor.textFaint)
                    .multilineTextAlignment(.center)
            }
            Spacer(minLength: 0)
        }
        .frame(maxWidth: .infinity)
        .frame(maxHeight: .infinity)
    }

    private var captureComposer: some View {
        HStack(spacing: 12) {
            Image(systemName: "plus.circle")
                .font(.system(size: 22, weight: .regular))
                .foregroundStyle(SiftColor.textMuted)

            TextField(
                "",
                text: $captureText,
                prompt: Text("Capture a concept…").foregroundColor(SiftColor.textFaint),
                axis: .vertical
            )
            .textFieldStyle(.plain)
            .font(SiftFont.body)
            .foregroundStyle(SiftColor.textPrimary)
            .tint(SiftColor.accent)
            .lineLimit(1...3)
            .accessibilityIdentifier("capture.input")

            Button {
                Task {
                    await toggleSpeechCapture()
                }
            } label: {
                Image(systemName: speechCapture.isRecording ? "mic.fill" : "mic")
                    .font(.system(size: 18, weight: .regular))
                    .frame(width: 28, height: 28)
            }
            .buttonStyle(.plain)
            .foregroundStyle(speechCapture.isRecording ? SiftColor.accent : SiftColor.textMuted)
            .disabled(isSubmitting)
            .accessibilityLabel(
                speechCapture.isRecording ? "Stop voice input" : "Start voice input"
            )

            Button {
                submitCapture()
            } label: {
                Group {
                    if isSubmitting {
                        ProgressView().tint(.white)
                    } else {
                        Image(systemName: "arrow.up")
                            .font(.system(size: 18, weight: .semibold))
                            .foregroundStyle(.white)
                    }
                }
                .frame(width: 40, height: 40)
                .background(
                    SiftColor.accent.opacity(canSubmit ? 1 : 0.4),
                    in: RoundedRectangle(cornerRadius: SiftRadius.send, style: .continuous)
                )
            }
            .buttonStyle(.plain)
            .disabled(isSubmitting || !canSubmit)
            .accessibilityLabel("Capture concept")
            .accessibilityIdentifier("capture.submit")
        }
        .padding(.leading, 16)
        .padding(.trailing, 8)
        .padding(.vertical, 8)
        .background(SiftColor.surfaceSoft, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
        .background(
            .ultraThinMaterial,
            in: RoundedRectangle(cornerRadius: 18, style: .continuous)
        )
        .overlay {
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .strokeBorder(SiftColor.hairline, lineWidth: 1)
        }
        .padding(.horizontal, 20)
        .padding(.bottom, SiftLayout.tabBarClearance)
    }

    private var canSubmit: Bool {
        !captureText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private func submitCapture() {
        guard !isSubmitting else { return }
        let rawCapture = captureText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !rawCapture.isEmpty else { return }
        isSubmitting = true
        Task {
            await captureConcept(rawCapture: rawCapture)
        }
    }

    private func captureConcept(rawCapture: String) async {
        speechCapture.stop()
        let service = CaptureFlowService(
            localStore: ConceptLocalStore(modelContext: modelContext),
            apiClient: appServices.apiClient
        )
        let draft: Concept

        defer { isSubmitting = false }
        errorMessage = nil
        do {
            switch try service.resolveCapture(rawCapture: rawCapture) {
            case .empty:
                return
            case .existing(let concept):
                captureText = ""
                onOpenConcept(concept.id, .followUp)
                return
            case .needsDisambiguation(_, let matches):
                errorMessage = "Possible matches found: \(matches.prefix(3).map(\.displayTitle).joined(separator: ", ")). Review this saved draft before generating."
                captureText = ""
                return
            case .newDraft(let newDraft):
                draft = newDraft
            }
        } catch {
            errorMessage = "Sift couldn’t start that capture. Try again."
            companion?.note(error)
            return
        }

        captureText = ""
        onOpenConcept(draft.id, .followUp)
        onGenerateConcept(draft)
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
            errorMessage = "Sift couldn’t start voice capture."
        }
    }

    private func refreshConcepts() async {
        do {
            let concepts = try await appServices.apiClient.listConcepts()
            let store = ConceptLocalStore(modelContext: modelContext)
            try store.upsertConcepts(from: concepts)
            try store.pruneLocalMirrorsMissingFromRemote(keeping: Set(concepts.map(\.id)))
            errorMessage = nil
            companion?.noteSuccess()
        } catch is CancellationError {
            return
        } catch {
            // Passive sync on the capture screen — stay quiet, just record it.
            companion?.note(error)
        }
    }
}

#Preview {
    NavigationStack {
        RecordView()
    }
    .environment(\.appServices, .preview)
}
