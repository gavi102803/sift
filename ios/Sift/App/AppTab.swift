import SwiftUI

enum AppTab: String, CaseIterable, Identifiable {
    case record
    case library
    case profile

    var id: String { rawValue }

    @ViewBuilder
    var content: some View {
        switch self {
        case .record:
            RecordView()
        case .library:
            ConceptLibraryView()
        case .profile:
            ProfileView()
        }
    }

    var label: some View {
        switch self {
        case .record:
            Label("Record", systemImage: "square.and.pencil")
        case .library:
            Label("Library", systemImage: "rectangle.stack")
        case .profile:
            Label("Profile", systemImage: "person")
        }
    }
}

