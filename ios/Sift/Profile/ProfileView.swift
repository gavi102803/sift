import SwiftUI

struct ProfileView: View {
    var body: some View {
        List {
            Section("Model Access") {
                LabeledContent("Gateway", value: "Sift Backend")
                LabeledContent("Explain Alias", value: "sift-explain")
                LabeledContent("Curate Alias", value: "sift-curate")
            }

            Section("Privacy") {
                Text("Provider API keys are managed by Sift Backend, not stored in the iOS app.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
        }
        .navigationTitle("Profile")
    }
}

#Preview {
    NavigationStack {
        ProfileView()
    }
}

