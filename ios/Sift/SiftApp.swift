import SwiftData
import SwiftUI

@main
struct SiftApp: App {
    private let modelContainer: ModelContainer

    init() {
        let schema = Schema([
            Concept.self,
            ConceptNote.self,
            NoteBlock.self,
            NoteRevision.self,
            UpdateEvent.self,
            Conversation.self,
            ModelThread.self,
            ConversationMessage.self,
            ModelRunMirror.self,
            ConceptUpdateProposal.self,
            AnswerSource.self,
            Tag.self,
            ConceptTag.self,
            Topic.self,
            ConceptTopic.self,
            ConceptRelation.self
        ])
#if DEBUG
        let isStoredInMemoryOnly = ProcessInfo.processInfo.environment["SIFT_UI_TEST_IN_MEMORY"] == "1"
        if ProcessInfo.processInfo.environment["SIFT_UI_TEST_RESET_MANAGED_CREDENTIALS"] == "1" {
            KeychainManagedCredentialStore.shared.resetForUITests()
        }
#else
        let isStoredInMemoryOnly = false
#endif
        let configuration = ModelConfiguration(
            schema: schema,
            isStoredInMemoryOnly: isStoredInMemoryOnly
        )
        do {
            modelContainer = try ModelContainer(for: schema, configurations: [configuration])
        } catch {
            fatalError("Failed to create Sift model container: \(error)")
        }
    }

    var body: some Scene {
        WindowGroup {
            AppView()
                .environment(\.appServices, .live)
        }
        .modelContainer(modelContainer)
    }
}
