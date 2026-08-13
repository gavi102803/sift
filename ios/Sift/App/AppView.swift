import SwiftUI
import SwiftData

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
    @Environment(\.appServices) private var appServices
    @Environment(\.modelContext) private var modelContext
    @State private var selectedTab: AppTab = .record
    @State private var librarySearchText = ""
    @State private var recordPath: [ConceptRoute] = []
    @State private var libraryPath: [UUID] = []
    @State private var companion = CompanionMonitor()
    @State private var managedAccessReady = false
    @AppStorage(AppTheme.storageKey) private var themeRaw = AppTheme.system.rawValue

    private var theme: AppTheme { AppTheme(rawValue: themeRaw) ?? .system }

    var body: some View {
        Group {
            if appServices.apiClient.requiresBetaActivation && !managedAccessReady {
                ManagedBetaOnboardingView(apiClient: appServices.apiClient) {
                    managedAccessReady = true
                    Task { await companion.refresh(using: appServices) }
                }
            } else {
                appContent
            }
        }
        .preferredColorScheme(theme.colorScheme)
        .tint(SiftColor.accent)
        .environment(companion)
    }

    private var appContent: some View {
        ZStack(alignment: .bottom) {
            ZStack {
                NavigationStack(path: $recordPath) {
                    RecordView(
                        onSearch: {
                            selectedTab = .library
                        },
                        onOpenConcept: { conceptId, initialMode in
                            recordPath.append(
                                ConceptRoute(id: conceptId, initialMode: initialMode)
                            )
                        },
                        onGenerateConcept: { draft in
                            startCaptureGeneration(for: draft)
                        }
                    )
                    .navigationDestination(for: ConceptRoute.self) { route in
                        ConceptDetailView(
                            conceptId: route.id,
                            initialMode: route.initialMode,
                            onConceptReplaced: { oldId, newId in
                                replaceLastConcept(in: &recordPath, oldId: oldId, newId: newId)
                            }
                        )
                    }
                }
                .tabPagePresentation(isSelected: selectedTab == .record)

                NavigationStack(path: $libraryPath) {
                    ConceptLibraryView(searchText: $librarySearchText)
                        .navigationDestination(for: UUID.self) { conceptId in
                            ConceptDetailView(
                                conceptId: conceptId,
                                onConceptReplaced: { oldId, newId in
                                    replaceLastConcept(in: &libraryPath, oldId: oldId, newId: newId)
                                }
                            )
                        }
                }
                .tabPagePresentation(isSelected: selectedTab == .library)

                NavigationStack {
                    ProfileView()
                }
                .tabPagePresentation(isSelected: selectedTab == .profile)
            }
            .animation(.smooth(duration: 0.34), value: selectedTab)

            FloatingTabBar(selection: $selectedTab)
        }
        .task {
            await companion.refresh(using: appServices)
            await recoverModelRuns()
        }
    }

    private func recoverModelRuns() async {
        guard let runs = try? await appServices.apiClient.listModelRuns(active: false) else { return }
        let store = ConceptLocalStore(modelContext: modelContext)
        for run in runs {
            _ = try? store.upsertModelRun(run)
            if run.status == "succeeded" {
                try? store.reconcileSucceededModelRun(run)
                replaceActiveDraftRoute(for: run)
            } else if run.status == "failed" {
                var remoteConcept: ConceptDTO?
                if run.kind == "initialConcept", let conceptId = run.conceptId {
                    remoteConcept = try? await appServices.apiClient.getConcept(id: conceptId)
                }
                try? store.reconcileFailedModelRun(run, remoteConcept: remoteConcept)
            } else if ["queued", "running", "waitingForCredential"].contains(run.status) {
                Task { await observeModelRun(run) }
            }
        }
        try? modelContext.save()
    }

    private func observeModelRun(_ initial: ModelRunDTO) async {
        var run = initial
        var activePollCount = 0
        let store = ConceptLocalStore(modelContext: modelContext)
        let mirror = try? store.upsertModelRun(run)
        var lastSequence = mirror?.lastSequence ?? 0
        do {
            while ["queued", "running", "waitingForCredential"].contains(run.status) {
                if run.status == "waitingForCredential" || activePollCount.isMultiple(of: 20) {
                    run = try await appServices.apiClient.resumeModelRun(id: run.id)
                } else {
                    try await Task.sleep(for: .milliseconds(250))
                    run = try await appServices.apiClient.getModelRun(id: run.id)
                }
                activePollCount += 1
                let events = try await appServices.apiClient.listModelRunEvents(
                    id: run.id,
                    afterSequence: lastSequence
                )
                for event in events where event.sequence > lastSequence {
                    lastSequence = event.sequence
                }
                _ = try store.upsertModelRun(run, lastSequence: lastSequence)
                try modelContext.save()
            }
            try store.reconcileSucceededModelRun(run)
            replaceActiveDraftRoute(for: run)
            try modelContext.save()
        } catch is CancellationError {
            return
        } catch {
            // The persisted mirror remains recoverable on the next app launch.
        }
    }

    private func startCaptureGeneration(for draft: Concept) {
        let draftId = draft.id
        Task { @MainActor in
            let service = CaptureFlowService(
                localStore: ConceptLocalStore(modelContext: modelContext),
                apiClient: appServices.apiClient
            )
            do {
                let generated = try await service.generateConcept(from: draft)
                companion.noteSuccess()
                replaceLastConcept(in: &recordPath, oldId: draftId, newId: generated.id)
            } catch is CancellationError {
                return
            } catch {
                // The durable draft remains visible and retryable from its detail page.
                companion.note(error)
            }
        }
    }

    private func replaceActiveDraftRoute(for run: ModelRunDTO) {
        guard run.kind == "initialConcept",
              run.status == "succeeded",
              let draftIdString = run.clientDraftId,
              let draftId = UUID(uuidString: draftIdString),
              let generatedId = run.result?.concept?.id else { return }
        replaceLastConcept(in: &recordPath, oldId: draftId, newId: generatedId)
    }

    private func replaceLastConcept(in path: inout [UUID], oldId: UUID, newId: UUID) {
        guard oldId != newId else { return }
        if path.last == oldId {
            path[path.count - 1] = newId
        }
    }

    private func replaceLastConcept(in path: inout [ConceptRoute], oldId: UUID, newId: UUID) {
        guard oldId != newId else { return }
        if path.last?.id == oldId {
            path[path.count - 1].id = newId
        }
    }
}

// MARK: - Floating tab bar

struct FloatingTabBar: View {
    @Binding var selection: AppTab
    @Namespace private var selectionGlass

    var body: some View {
        Group {
            if #available(iOS 26.0, *) {
                GlassEffectContainer(spacing: 10) {
                    tabItems(usesNativeGlass: true)
                        .glassEffect(.regular, in: .rect(cornerRadius: 30))
                }
            } else {
                tabItems(usesNativeGlass: false)
                    .background(.ultraThinMaterial, in: Capsule(style: .continuous))
                    .overlay(
                        Capsule(style: .continuous)
                            .strokeBorder(Color.primary.opacity(0.06), lineWidth: 1)
                    )
            }
        }
        .siftTabBarShadow()
        .padding(.horizontal, 70)
        .padding(.bottom, 18)
    }

    private func tabItems(usesNativeGlass: Bool) -> some View {
        HStack(spacing: 0) {
            ForEach(AppTab.allCases) { tab in
                FloatingTabItem(
                    tab: tab,
                    isActive: selection == tab,
                    selectionGlass: selectionGlass,
                    usesNativeGlass: usesNativeGlass
                ) {
                    if selection != tab {
                        withAnimation(.smooth(duration: 0.34)) {
                            selection = tab
                        }
                    }
                }
            }
        }
        .frame(maxWidth: .infinity)
        .frame(height: 60)
    }
}

private struct FloatingTabItem: View {
    let tab: AppTab
    let isActive: Bool
    let selectionGlass: Namespace.ID
    let usesNativeGlass: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(spacing: 3) {
                glyph
                Text(tab.title)
                    .font(SiftFont.tabLabel)
                    .foregroundStyle(isActive ? SiftColor.textPrimary : SiftColor.textFaint)
            }
            .padding(.vertical, 6)
            .padding(.horizontal, 16)
            .background { activeBackground }
            .frame(maxWidth: .infinity)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(tab.title)
        .accessibilityAddTraits(isActive ? [.isSelected] : [])
    }

    @ViewBuilder
    private var activeBackground: some View {
        if isActive {
            if #available(iOS 26.0, *), usesNativeGlass {
                Color.clear
                    .glassEffect(
                        .regular.tint(SiftColor.surfaceSoftHi.opacity(0.72)).interactive(),
                        in: .rect(cornerRadius: 22)
                    )
                    .glassEffectID("selected-tab", in: selectionGlass)
            } else {
                Capsule(style: .continuous)
                    .fill(SiftColor.surfaceSoftHi)
                    .matchedGeometryEffect(id: "selected-tab", in: selectionGlass)
            }
        }
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

private extension View {
    func tabPagePresentation(isSelected: Bool) -> some View {
        opacity(isSelected ? 1 : 0)
            .scaleEffect(isSelected ? 1 : 0.985)
            .blur(radius: isSelected ? 0 : 3)
            .allowsHitTesting(isSelected)
            .accessibilityHidden(!isSelected)
            .zIndex(isSelected ? 1 : 0)
    }
}

#Preview {
    AppView()
        .environment(\.appServices, .preview)
}
