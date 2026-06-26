import SwiftUI

enum AppTab: String, CaseIterable, Identifiable {
    case record
    case library
    case profile

    var id: String { rawValue }

    var label: some View {
        switch self {
        case .record:
            Label("Capture", systemImage: "plus.circle")
        case .library:
            Label("Library", systemImage: "books.vertical")
        case .profile:
            Label("Profile", systemImage: "person.fill")
        }
    }
}
