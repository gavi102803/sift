import SwiftUI

private struct ConceptRoute: Hashable {
    var id: UUID
    var initialMode: ConceptDetailMode
}

struct AppView: View {
    @State private var selectedTab: AppTab = .record
    @State private var librarySearchText = ""
    @State private var recordPath: [ConceptRoute] = []
    @State private var libraryPath: [UUID] = []

    var body: some View {
        TabView(selection: $selectedTab) {
            NavigationStack(path: $recordPath) {
                RecordView(
                    onSearch: {
                        selectedTab = .library
                    },
                    onOpenConcept: { conceptId, initialMode in
                        recordPath.append(ConceptRoute(id: conceptId, initialMode: initialMode))
                    },
                    onReplaceOpenedConcept: { oldId, newId in
                        replaceLastConcept(in: &recordPath, oldId: oldId, newId: newId)
                    }
                )
                .navigationDestination(for: ConceptRoute.self) { route in
                    ConceptDetailView(conceptId: route.id, initialMode: route.initialMode)
                }
            }
            .tabItem { AppTab.record.label }
            .tag(AppTab.record)

            NavigationStack(path: $libraryPath) {
                ConceptLibraryView(searchText: $librarySearchText)
                    .navigationDestination(for: UUID.self) { conceptId in
                        ConceptDetailView(conceptId: conceptId)
                    }
            }
            .tabItem { AppTab.library.label }
            .tag(AppTab.library)

            NavigationStack {
                ProfileView()
            }
            .tabItem { AppTab.profile.label }
            .tag(AppTab.profile)
        }
    }

    private func replaceLastConcept(in path: inout [ConceptRoute], oldId: UUID, newId: UUID) {
        guard oldId != newId else { return }
        if path.last?.id == oldId {
            path[path.count - 1].id = newId
        } else {
            path.append(ConceptRoute(id: newId, initialMode: .followUp))
        }
    }
}

#Preview {
    AppView()
}
