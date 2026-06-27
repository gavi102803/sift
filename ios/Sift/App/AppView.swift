import SwiftUI

private struct ConceptRoute: Hashable {
    var id: UUID
    var initialMode: ConceptDetailMode
}

/// Height the floating tab bar occupies above the safe-area bottom.
/// Used by root screens to keep content / composers clear of the bar.
enum SiftLayout {
    static let tabBarClearance: CGFloat = 92
}

struct AppView: View {
    @State private var selectedTab: AppTab = .record
    @State private var librarySearchText = ""
    @State private var recordPath: [ConceptRoute] = []
    @State private var libraryPath: [UUID] = []

    var body: some View {
        ZStack(alignment: .bottom) {
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
                .toolbar(.hidden, for: .tabBar)
                .tag(AppTab.record)

                NavigationStack(path: $libraryPath) {
                    ConceptLibraryView(searchText: $librarySearchText)
                        .navigationDestination(for: UUID.self) { conceptId in
                            ConceptDetailView(conceptId: conceptId)
                        }
                }
                .toolbar(.hidden, for: .tabBar)
                .tag(AppTab.library)

                NavigationStack {
                    ProfileView()
                }
                .toolbar(.hidden, for: .tabBar)
                .tag(AppTab.profile)
            }

            FloatingTabBar(selection: $selectedTab)
        }
        .preferredColorScheme(.dark)
        .tint(SiftColor.accent)
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

// MARK: - Floating tab bar

struct FloatingTabBar: View {
    @Binding var selection: AppTab

    var body: some View {
        HStack(spacing: 6) {
            ForEach(AppTab.allCases) { tab in
                FloatingTabItem(
                    tab: tab,
                    isActive: selection == tab
                ) {
                    if selection != tab {
                        withAnimation(.spring(response: 0.32, dampingFraction: 0.86)) {
                            selection = tab
                        }
                    }
                }
            }
        }
        .padding(.horizontal, 8)
        .frame(height: 66)
        .background(
            Color(hex: 0x14161A, alpha: 0.72),
            in: RoundedRectangle(cornerRadius: SiftRadius.tabBar, style: .continuous)
        )
        .background(
            .ultraThinMaterial,
            in: RoundedRectangle(cornerRadius: SiftRadius.tabBar, style: .continuous)
        )
        .overlay(
            RoundedRectangle(cornerRadius: SiftRadius.tabBar, style: .continuous)
                .strokeBorder(Color.white.opacity(0.08), lineWidth: 1)
        )
        .siftTabBarShadow()
        .padding(.horizontal, 16)
        .padding(.bottom, 18)
    }
}

private struct FloatingTabItem: View {
    let tab: AppTab
    let isActive: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(spacing: 4) {
                glyph
                Text(tab.title)
                    .font(SiftFont.tabLabel)
                    .foregroundStyle(isActive ? SiftColor.textPrimary : SiftColor.textFaint)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 8)
            .background(
                Group {
                    if isActive {
                        RoundedRectangle(cornerRadius: SiftRadius.tabItem, style: .continuous)
                            .fill(SiftColor.surfaceSoftHi)
                    }
                }
            )
        }
        .buttonStyle(.plain)
        .accessibilityLabel(tab.title)
        .accessibilityAddTraits(isActive ? [.isSelected] : [])
    }

    @ViewBuilder
    private var glyph: some View {
        if tab == .record {
            // Capture icon always sits in an accent rounded-square tile.
            RoundedRectangle(cornerRadius: 9, style: .continuous)
                .fill(SiftColor.accent)
                .frame(width: 30, height: 30)
                .overlay(
                    Image(systemName: "plus")
                        .font(.system(size: 16, weight: .semibold))
                        .foregroundStyle(.white)
                )
        } else {
            Image(systemName: tab.systemImage)
                .font(.system(size: 19, weight: .regular))
                .frame(height: 30)
                .foregroundStyle(isActive ? SiftColor.textPrimary : SiftColor.textFaint)
        }
    }
}

#Preview {
    AppView()
        .environment(\.appServices, .preview)
}
