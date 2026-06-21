import SwiftUI

struct AppView: View {
    @State private var selectedTab: AppTab = .record

    var body: some View {
        TabView(selection: $selectedTab) {
            ForEach(AppTab.allCases) { tab in
                NavigationStack {
                    tab.content
                }
                .tabItem { tab.label }
                .tag(tab)
            }
        }
    }
}

#Preview {
    AppView()
}

