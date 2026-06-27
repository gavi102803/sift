#if DEBUG
import SwiftUI

#Preview("Profile") {
    NavigationStack {
        ProfileView()
    }
    .environment(\.appServices, .preview)
    .preferredColorScheme(.dark)
}

#Preview("Active Model") {
    NavigationStack {
        ModelProviderSettingsView()
    }
    .environment(\.appServices, .preview)
    .preferredColorScheme(.dark)
}

#Preview("Research") {
    NavigationStack {
        WebSearchSettingsView()
    }
    .environment(\.appServices, .preview)
    .preferredColorScheme(.dark)
}

#Preview("Advanced Connections") {
    NavigationStack {
        AdvancedConnectionsView()
    }
    .environment(\.appServices, .preview)
    .preferredColorScheme(.dark)
}

#Preview("Developer") {
    NavigationStack {
        DeveloperToolsView()
    }
    .environment(\.appServices, .preview)
    .preferredColorScheme(.dark)
}
#endif
