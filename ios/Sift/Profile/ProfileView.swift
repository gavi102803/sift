import SwiftUI

struct ProfileView: View {
    @Environment(\.appServices) private var appServices
    @State private var appStatus: AppStatusDTO?
    @State private var modelSettings: ModelProviderSettingsDTO?
    @State private var webSettings: WebProviderSettingsDTO?
    @State private var errorMessage: String?
    @State private var isRefreshing = false
    @AppStorage(AppTheme.storageKey) private var themeRaw = AppTheme.system.rawValue

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                Text("Profile")
                    .font(SiftFont.screenTitle)
                    .tracking(-0.8)
                    .foregroundStyle(SiftColor.textPrimary)
                    .padding(.top, 8)

                identityCard
                aiSection
                appearanceSection
                developerSection

                if let errorMessage {
                    InlineErrorView(message: errorMessage) {
                        Task { await refresh() }
                    }
                }
            }
            .padding(.horizontal, 20)
            .padding(.top, 8)
            .padding(.bottom, SiftLayout.tabBarClearance)
        }
        .scrollContentBackground(.hidden)
        .siftScreenBackground()
        .navigationBarHidden(true)
        .refreshable { await refresh() }
        .task { await refresh() }
    }

    // MARK: Identity

    private var identityCard: some View {
        HStack(spacing: 14) {
            SiftSymbol(size: 36)
                .frame(width: 46, height: 46)
                .background(SiftColor.accentWash, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                .overlay {
                    RoundedRectangle(cornerRadius: 12, style: .continuous)
                        .strokeBorder(SiftColor.accentBorder, lineWidth: 1)
                }

            VStack(alignment: .leading, spacing: 3) {
                Text("Sift")
                    .font(SiftFont.sans(16, .semibold))
                    .foregroundStyle(SiftColor.textPrimary)
                Text("Your knowledge, on this device")
                    .font(SiftFont.cardDesc)
                    .foregroundStyle(SiftColor.textFaint)
            }
            Spacer()
        }
        .padding(16)
        .background(SiftColor.surface, in: RoundedRectangle(cornerRadius: SiftRadius.card, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: SiftRadius.card, style: .continuous)
                .strokeBorder(SiftColor.hairline, lineWidth: 1)
        }
        .siftCardShadow()
    }

    // MARK: AI & Research

    private var aiSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            SiftEyebrow(text: "AI & Research")
            SiftGroupedCard {
                NavigationLink {
                    ModelProviderSettingsView()
                } label: {
                    SiftSettingRow(icon: "cpu", title: "Active Model") {
                        HStack(spacing: 8) {
                            ProviderBrandMark(providerId: providerId, size: 18, cornerRadius: 5)
                            Text(modelLabel)
                                .font(SiftFont.mono(12))
                                .foregroundStyle(SiftColor.textBody)
                                .lineLimit(1)
                        }
                    }
                }
                .buttonStyle(.plain)

                SiftGroupDivider()

                NavigationLink {
                    WebSearchSettingsView()
                } label: {
                    SiftSettingRow(icon: "globe", title: "Research") {
                        Text(webLabel)
                            .font(SiftFont.mono(12))
                            .foregroundStyle(SiftColor.textBody)
                    }
                }
                .buttonStyle(.plain)

                SiftGroupDivider()

                NavigationLink {
                    AdvancedConnectionsView()
                } label: {
                    SiftSettingRow(icon: "slider.horizontal.3", title: "Advanced Connections")
                }
                .buttonStyle(.plain)
            }
        }
    }

    // MARK: Appearance

    private var appearanceSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            SiftEyebrow(text: "Appearance")
            SiftGroupedCard {
                NavigationLink {
                    AppearanceSettingsView()
                } label: {
                    SiftSettingRow(icon: "paintbrush", title: "Appearance") {
                        Text((AppTheme(rawValue: themeRaw) ?? .system).label)
                            .font(SiftFont.mono(12))
                            .foregroundStyle(SiftColor.textBody)
                    }
                }
                .buttonStyle(.plain)
            }
        }
    }

    // MARK: Developer

    private var developerSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            SiftEyebrow(text: "Developer")
            SiftGroupedCard {
                NavigationLink {
                    DeveloperToolsView()
                } label: {
                    SiftSettingRow(icon: "wrench.and.screwdriver", title: "Developer tools")
                }
                .buttonStyle(.plain)
            }
        }
    }

    // MARK: Derived labels

    private var providerId: String {
        modelSettings?.providerType ?? appStatus?.modelProvider ?? "—"
    }

    private var modelLabel: String {
        modelSettings?.explainModel ?? appStatus?.explainModel ?? providerId
    }

    private var webLabel: String {
        guard let webSettings else {
            return appStatus?.webSearchEnabled == true ? "on" : "off"
        }
        return webSettings.webSearchEnabled ? webSettings.providerType : "off"
    }

    private func refresh() async {
        guard !isRefreshing else { return }
        isRefreshing = true
        defer { isRefreshing = false }
        errorMessage = nil
        do {
            async let status = appServices.apiClient.getAppStatus()
            async let model = appServices.apiClient.getModelProviderSettings()
            async let web = appServices.apiClient.getWebProviderSettings()
            appStatus = try await status
            modelSettings = try await model
            webSettings = try await web
        } catch is CancellationError {
            return
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
