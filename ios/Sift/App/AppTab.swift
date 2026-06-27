import SwiftUI

enum AppTab: String, CaseIterable, Identifiable {
    case record
    case library
    case profile

    var id: String { rawValue }

    var title: String {
        switch self {
        case .record: "Capture"
        case .library: "Library"
        case .profile: "Profile"
        }
    }

    /// SF Symbol approximating the lucide icon used in the mock.
    var systemImage: String {
        switch self {
        case .record: "plus"
        case .library: "books.vertical"
        case .profile: "person"
        }
    }
}
