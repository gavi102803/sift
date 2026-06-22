import SwiftData
import SwiftUI

@main
struct SiftApp: App {
    var body: some Scene {
        WindowGroup {
            AppView()
                .environment(\.appServices, .live)
        }
        .modelContainer(for: [
            Concept.self,
            ConceptNote.self,
            NoteBlock.self,
            NoteRevision.self,
            UpdateEvent.self,
            Conversation.self,
            ModelThread.self,
            ConversationMessage.self,
            ConceptUpdateProposal.self,
            AnswerSource.self,
            Tag.self,
            ConceptTag.self,
            Topic.self,
            ConceptTopic.self,
            ConceptRelation.self
        ])
    }
}
