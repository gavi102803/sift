import SwiftUI

struct ProfileView: View {
    @Environment(\.appServices) private var appServices
    @State private var appStatus: AppStatusDTO?
    @State private var modelSettings: ModelProviderSettingsDTO?
    @State private var webSettings: WebProviderSettingsDTO?
    @State private var diagnostic: ModelDiagnosticDTO?
    @State private var webDiagnostic: ModelDiagnosticDTO?
    @State private var errorMessage: String?
    @State private var isRefreshing = false
    @State private var isTestingModel = false
    @State private var isTestingWeb = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                Text("Profile")
                    .font(SiftFont.screenTitle)
                    .tracking(-0.8)
                    .foregroundStyle(SiftColor.textPrimary)
                    .padding(.top, 8)

                NavigationLink {
                    AccountDetailView(appStatus: appStatus)
                } label: {
                    profileHeader
                }
                .buttonStyle(.plain)

                runtimeSection
                diagnosticsSection
                privacySection
            }
            .padding(.horizontal, 20)
            .padding(.top, 8)
            .padding(.bottom, SiftLayout.tabBarClearance)
        }
        .scrollContentBackground(.hidden)
        .siftScreenBackground()
        .navigationBarHidden(true)
        .refreshable {
            await refresh()
        }
        .task {
            await refresh()
        }
    }

    private var profileHeader: some View {
        HStack(spacing: 14) {
            SiftSymbol(size: 36)
                .frame(width: 46, height: 46)
                .background(SiftColor.accentWash, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                .overlay {
                    RoundedRectangle(cornerRadius: 12, style: .continuous)
                        .strokeBorder(SiftColor.accentBorder, lineWidth: 1)
                }

            VStack(alignment: .leading, spacing: 3) {
                Text("Sift User")
                    .font(SiftFont.sans(16, .semibold))
                    .foregroundStyle(SiftColor.textPrimary)
                Text(appStatus?.env ?? "development")
                    .font(SiftFont.cardDesc)
                    .foregroundStyle(SiftColor.textFaint)
            }

            Spacer()
            Image(systemName: "chevron.right")
                .font(.system(size: 14, weight: .semibold))
                .foregroundStyle(SiftColor.textFaint)
        }
        .padding(16)
        .background(SiftColor.surface, in: RoundedRectangle(cornerRadius: SiftRadius.card, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: SiftRadius.card, style: .continuous)
                .strokeBorder(SiftColor.hairline, lineWidth: 1)
        }
        .siftCardShadow()
    }

    private var runtimeSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            SiftEyebrow(text: "Runtime")
            SiftGroupedCard {
                NavigationLink {
                    ModelProviderSettingsView()
                } label: {
                    SiftSettingRow(icon: "cpu", title: "Model Provider") {
                        HStack(spacing: 8) {
                            ProviderBrandMark(providerId: providerId, size: 18, cornerRadius: 5)
                            Text(providerId)
                                .font(SiftFont.mono(12))
                                .foregroundStyle(SiftColor.textBody)
                        }
                    }
                }
                .buttonStyle(.plain)

                SiftGroupDivider()

                NavigationLink {
                    WebSearchSettingsView()
                } label: {
                    SiftSettingRow(icon: "globe", title: "Web Search") {
                        Text(webSettingsLabel)
                            .font(SiftFont.mono(12))
                            .foregroundStyle(SiftColor.textBody)
                    }
                }
                .buttonStyle(.plain)
            }
        }
    }

    private var diagnosticsSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            SiftEyebrow(text: "Diagnostics")
            HStack(spacing: 10) {
                SiftButton(
                    title: "Test model",
                    systemImage: "testtube.2",
                    kind: .primary,
                    height: 44,
                    isLoading: isTestingModel
                ) {
                    Task { await runModelDiagnostic() }
                }

                SiftButton(
                    title: "Web search",
                    systemImage: "globe",
                    kind: .secondary,
                    height: 44,
                    isLoading: isTestingWeb
                ) {
                    Task { await runWebDiagnostic() }
                }
            }

            if let diagnostic {
                DiagnosticAlert(diagnostic: diagnostic)
            }
            if let webDiagnostic {
                DiagnosticAlert(diagnostic: webDiagnostic)
            }
            if let errorMessage {
                InlineErrorView(message: errorMessage) {
                    Task { await refresh() }
                }
            }
        }
    }

    private var privacySection: some View {
        VStack(alignment: .leading, spacing: 10) {
            SiftEyebrow(text: "Privacy")
            HStack(alignment: .top, spacing: 12) {
                Image(systemName: "lock")
                    .font(.system(size: 16, weight: .regular))
                    .foregroundStyle(SiftColor.textMuted)
                    .padding(.top, 1)
                Text("Runtime API keys are stored by Sift Backend and returned to iOS only as a masked preview.")
                    .font(SiftFont.cardDesc)
                    .foregroundStyle(SiftColor.textMuted)
                    .lineSpacing(2)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(14)
            .background(SiftColor.surfaceSoft, in: RoundedRectangle(cornerRadius: SiftRadius.card, style: .continuous))
            .overlay {
                RoundedRectangle(cornerRadius: SiftRadius.card, style: .continuous)
                    .strokeBorder(SiftColor.hairline, lineWidth: 1)
            }
        }
    }

    private var providerId: String {
        modelSettings?.providerType ?? appStatus?.modelProvider ?? "—"
    }

    private var webSettingsLabel: String {
        guard let webSettings else {
            return appStatus?.webSearchEnabled == true ? "on" : "off"
        }
        return webSettings.webSearchEnabled ? webSettings.providerType : "off"
    }

    private func refresh() async {
        guard !isRefreshing else { return }
        isRefreshing = true
        defer {
            isRefreshing = false
        }
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

    private func runModelDiagnostic() async {
        guard !isTestingModel else { return }
        isTestingModel = true
        defer {
            isTestingModel = false
        }
        errorMessage = nil
        do {
            diagnostic = try await appServices.apiClient.runModelDiagnostic()
        } catch is CancellationError {
            return
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func runWebDiagnostic() async {
        guard !isTestingWeb else { return }
        isTestingWeb = true
        defer {
            isTestingWeb = false
        }
        errorMessage = nil
        do {
            webDiagnostic = try await appServices.apiClient.runWebSearchDiagnostic()
        } catch is CancellationError {
            return
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

// MARK: - Account detail (pushed from the user card)

private struct AccountDetailView: View {
    var appStatus: AppStatusDTO?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                SiftEyebrow(text: "Account")
                SiftGroupedCard {
                    SiftSettingRow(icon: "person", title: "Name", showsChevron: false) {
                        Text("Sift User")
                            .font(SiftFont.body)
                            .foregroundStyle(SiftColor.textBody)
                    }
                    SiftGroupDivider()
                    SiftSettingRow(icon: "hammer", title: "Environment", showsChevron: false) {
                        Text(appStatus?.env ?? "development")
                            .font(SiftFont.mono(12))
                            .foregroundStyle(SiftColor.textBody)
                    }
                }
            }
            .padding(.horizontal, 20)
            .padding(.top, 12)
            .padding(.bottom, SiftLayout.tabBarClearance)
        }
        .scrollContentBackground(.hidden)
        .siftScreenBackground()
        .navigationTitle("Account")
        .navigationBarTitleDisplayMode(.inline)
    }
}

// MARK: - Model provider settings (screen 06)

private struct ModelProviderSettingsView: View {
    @Environment(\.appServices) private var appServices
    @State private var providers: [RuntimeProviderOptionDTO] = []
    @State private var settings: ModelProviderSettingsDTO?
    @State private var providerType = "deepseek"
    @State private var baseURL = ""
    @State private var apiKey = ""
    @State private var model = ""
    @State private var providerModels: [ProviderModelDTO] = []
    @State private var errorMessage: String?
    @State private var isLoading = false
    @State private var isSaving = false
    @State private var isLoadingModels = false
    @State private var picker: ProviderPickerPresentation?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                SiftEyebrow(text: "Configuration")
                    .padding(.bottom, 2)

                SiftGroupedCard {
                    Button {
                        picker = ProviderPickerPresentation()
                    } label: {
                        SiftSettingRow(icon: "cpu", title: "Provider") {
                            HStack(spacing: 8) {
                                ProviderBrandMark(providerId: providerType, size: 18, cornerRadius: 5)
                                Text(selectedProvider?.name ?? providerType)
                                    .font(SiftFont.body)
                                    .foregroundStyle(SiftColor.textBody)
                            }
                        }
                    }
                    .buttonStyle(.plain)

                    SiftGroupDivider()
                    fieldRow(label: "Base URL") {
                        TextField("", text: $baseURL, prompt: Text("https://…").foregroundColor(SiftColor.textFaint))
                            .textFieldStyle(.plain)
                            .font(SiftFont.mono(13))
                            .foregroundStyle(SiftColor.textSecondary)
                            .tint(SiftColor.accent)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .disabled(selectedProvider?.adapter == "mock")
                    }

                    SiftGroupDivider()
                    fieldRow(label: "API Key") {
                        SecureField(apiKeyPlaceholder, text: $apiKey)
                            .textFieldStyle(.plain)
                            .font(SiftFont.mono(13))
                            .foregroundStyle(SiftColor.textSecondary)
                            .tint(SiftColor.accent)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .disabled(selectedProvider?.requiresApiKey == false)
                    }

                    SiftGroupDivider()
                    fieldRow(label: "Model") {
                        HStack(spacing: 8) {
                            TextField("", text: $model, prompt: Text("model-id").foregroundColor(SiftColor.textFaint))
                                .textFieldStyle(.plain)
                                .font(SiftFont.mono(13))
                                .foregroundStyle(SiftColor.textSecondary)
                                .tint(SiftColor.accent)
                                .textInputAutocapitalization(.never)
                                .autocorrectionDisabled()

                            Menu {
                                if providerModels.isEmpty {
                                    Text("No models loaded")
                                } else {
                                    ForEach(providerModels) { option in
                                        Button(option.id) {
                                            model = option.id
                                        }
                                    }
                                }
                            } label: {
                                Image(systemName: "list.bullet")
                                    .font(.system(size: 15, weight: .medium))
                                    .foregroundStyle(providerModels.isEmpty ? SiftColor.textFaint : SiftColor.accent)
                            }
                            .disabled(providerModels.isEmpty)
                            .accessibilityLabel("Choose model")
                        }
                    }
                }

                VStack(spacing: 10) {
                    SiftButton(
                        title: "Load models",
                        systemImage: "arrow.down.circle",
                        kind: .secondary,
                        isLoading: isLoadingModels
                    ) {
                        Task { await loadModels() }
                    }
                    .disabled(isLoadingModels || selectedProvider?.supportsModelListing == false)

                    SiftButton(
                        title: "Save changes",
                        systemImage: "checkmark",
                        kind: .primary,
                        isLoading: isSaving
                    ) {
                        Task { await save() }
                    }
                    .disabled(isSaving || !canSave)
                }
                .padding(.top, 6)

                if let errorMessage {
                    InlineErrorView(message: errorMessage) {
                        Task { await load() }
                    }
                }
            }
            .padding(.horizontal, 20)
            .padding(.top, 12)
            .padding(.bottom, SiftLayout.tabBarClearance)
        }
        .scrollContentBackground(.hidden)
        .siftScreenBackground()
        .navigationTitle("Model Provider")
        .navigationBarTitleDisplayMode(.inline)
        .task {
            await load()
        }
        .sheet(item: $picker) { _ in
            ProviderPickerSheet(
                title: "Select Provider",
                providers: visibleProviders,
                selectedID: providerType
            ) { provider in
                apply(provider)
            }
            .presentationDetents([.medium, .large])
            .presentationDragIndicator(.hidden)
        }
    }

    @ViewBuilder
    private func fieldRow<Content: View>(label: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(label.uppercased())
                .font(SiftFont.fieldLabel)
                .tracking(0.5)
                .foregroundStyle(SiftColor.textFaintest)
            content()
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 14)
        .padding(.vertical, 13)
    }

    private var visibleProviders: [RuntimeProviderOptionDTO] {
        providers.filter { provider in
            provider.id != "mock"
        }.sorted { left, right in
            if left.status != right.status {
                return left.status < right.status
            }
            if left.isAdvanced != right.isAdvanced {
                return !left.isAdvanced
            }
            return left.name < right.name
        }
    }

    private var selectedProvider: RuntimeProviderOptionDTO? {
        providers.first { $0.id == providerType }
    }

    private var apiKeyPlaceholder: String {
        if let preview = selectedProvider?.apiKeyPreview ?? settings?.apiKeyPreview {
            return "•••••••••••• \(preview)"
        }
        return "API Key"
    }

    private var canSave: Bool {
        guard selectedProvider?.adapter != "mock" else { return true }
        return !baseURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && !model.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private func load() async {
        guard !isLoading else { return }
        isLoading = true
        defer {
            isLoading = false
        }
        errorMessage = nil
        do {
            async let catalog = appServices.apiClient.listRuntimeModelProviders()
            async let providerSettings = appServices.apiClient.getModelProviderSettings()
            providers = try await catalog.providers
            applySettings(try await providerSettings)
        } catch is CancellationError {
            return
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func applySettings(_ settings: ModelProviderSettingsDTO) {
        self.settings = settings
        providerType = settings.providerType
        baseURL = settings.baseURL
        apiKey = ""
        model = settings.explainModel
    }

    private func apply(_ provider: RuntimeProviderOptionDTO) {
        providerType = provider.id
        baseURL = provider.configuredBaseURL ?? provider.defaultBaseURL
        model = provider.configuredModel ?? provider.defaultModel
        apiKey = ""
        providerModels = []
        picker = nil
    }

    private func loadModels() async {
        guard !isLoadingModels else { return }
        isLoadingModels = true
        defer {
            isLoadingModels = false
        }
        errorMessage = nil
        do {
            _ = try await save(silent: true)
            providerModels = try await appServices.apiClient.listProviderModels().models
        } catch is CancellationError {
            return
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    @discardableResult
    private func save(silent: Bool = false) async throws -> ModelProviderSettingsDTO {
        guard !isSaving else {
            if let settings { return settings }
            throw SiftProfileError.saveInProgress
        }
        isSaving = true
        defer {
            isSaving = false
        }
        if !silent {
            errorMessage = nil
        }
        let updated = try await appServices.apiClient.updateModelProviderSettings(
            UpdateModelProviderSettingsRequest(
                providerType: providerType,
                baseURL: baseURL.trimmingCharacters(in: .whitespacesAndNewlines),
                apiKey: apiKey.isEmpty ? nil : apiKey,
                explainModel: model.trimmingCharacters(in: .whitespacesAndNewlines),
                webSearchEnabled: settings?.webSearchEnabled ?? true
            )
        )
        applySettings(updated)
        return updated
    }

    private func save() async {
        do {
            _ = try await save(silent: false)
        } catch is CancellationError {
            return
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

// MARK: - Web search settings

private struct WebSearchSettingsView: View {
    @Environment(\.appServices) private var appServices
    @State private var providers: [WebProviderOptionDTO] = []
    @State private var settings: WebProviderSettingsDTO?
    @State private var providerType = "ddgs"
    @State private var apiKey = ""
    @State private var isEnabled = true
    @State private var errorMessage: String?
    @State private var isLoading = false
    @State private var isSaving = false
    @State private var picker: WebProviderPickerPresentation?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                SiftGroupedCard {
                    SiftSettingRow(icon: "globe", title: "Web Search", showsChevron: false) {
                        Toggle("", isOn: $isEnabled)
                            .labelsHidden()
                            .tint(SiftColor.accent)
                    }
                }

                SiftEyebrow(text: "Configuration")
                    .padding(.top, 4)

                SiftGroupedCard {
                    Button {
                        picker = WebProviderPickerPresentation()
                    } label: {
                        SiftSettingRow(icon: "magnifyingglass", title: "Provider") {
                            Text(selectedProvider?.name ?? providerType)
                                .font(SiftFont.body)
                                .foregroundStyle(SiftColor.textBody)
                        }
                    }
                    .buttonStyle(.plain)

                    if selectedProvider?.requiresApiKey == true {
                        SiftGroupDivider()
                        VStack(alignment: .leading, spacing: 6) {
                            Text("API KEY")
                                .font(SiftFont.fieldLabel)
                                .tracking(0.5)
                                .foregroundStyle(SiftColor.textFaintest)
                            SecureField(apiKeyPlaceholder, text: $apiKey)
                                .textFieldStyle(.plain)
                                .font(SiftFont.mono(13))
                                .foregroundStyle(SiftColor.textSecondary)
                                .tint(SiftColor.accent)
                                .textInputAutocapitalization(.never)
                                .autocorrectionDisabled()
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.horizontal, 14)
                        .padding(.vertical, 13)
                    }
                }

                SiftButton(
                    title: "Save changes",
                    systemImage: "checkmark",
                    kind: .primary,
                    isLoading: isSaving
                ) {
                    Task { await save() }
                }
                .disabled(isSaving || selectedProvider?.status == "comingSoon")
                .padding(.top, 6)

                if let errorMessage {
                    InlineErrorView(message: errorMessage) {
                        Task { await load() }
                    }
                }
            }
            .padding(.horizontal, 20)
            .padding(.top, 12)
            .padding(.bottom, SiftLayout.tabBarClearance)
        }
        .scrollContentBackground(.hidden)
        .siftScreenBackground()
        .navigationTitle("Web Search")
        .navigationBarTitleDisplayMode(.inline)
        .task {
            await load()
        }
        .sheet(item: $picker) { _ in
            WebProviderPickerSheet(
                title: "Web Search Provider",
                providers: visibleProviders,
                selectedID: providerType
            ) { provider in
                apply(provider)
            }
            .presentationDetents([.medium])
            .presentationDragIndicator(.hidden)
        }
    }

    private var selectedProvider: WebProviderOptionDTO? {
        providers.first { $0.id == providerType }
    }

    private var apiKeyPlaceholder: String {
        if let preview = selectedProvider?.apiKeyPreview ?? settings?.apiKeyPreview {
            return "•••••••••••• \(preview)"
        }
        return "API Key"
    }

    private func load() async {
        guard !isLoading else { return }
        isLoading = true
        defer {
            isLoading = false
        }
        errorMessage = nil
        do {
            async let catalog = appServices.apiClient.listRuntimeWebProviders()
            async let webSettings = appServices.apiClient.getWebProviderSettings()
            providers = try await catalog.providers
            applySettings(try await webSettings)
        } catch is CancellationError {
            return
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func applySettings(_ settings: WebProviderSettingsDTO) {
        self.settings = settings
        providerType = settings.providerType
        isEnabled = settings.webSearchEnabled
        apiKey = ""
    }

    private func apply(_ provider: WebProviderOptionDTO) {
        providerType = provider.id
        apiKey = ""
        picker = nil
    }

    private func save() async {
        guard !isSaving else { return }
        isSaving = true
        defer {
            isSaving = false
        }
        errorMessage = nil
        do {
            let updated = try await appServices.apiClient.updateWebProviderSettings(
                UpdateWebProviderSettingsRequest(
                    providerType: providerType,
                    apiKey: apiKey.isEmpty ? nil : apiKey,
                    webSearchEnabled: isEnabled
                )
            )
            applySettings(updated)
        } catch is CancellationError {
            return
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private var visibleProviders: [WebProviderOptionDTO] {
        providers.filter { provider in
            provider.id != "disabled"
        }
    }
}

private struct ProviderPickerPresentation: Identifiable {
    let id = UUID()
}

private struct WebProviderPickerPresentation: Identifiable {
    let id = UUID()
}

// MARK: - Provider picker bottom sheet (screen 07)

private struct ProviderPickerSheet: View {
    @Environment(\.dismiss) private var dismiss
    var title: String
    var providers: [RuntimeProviderOptionDTO]
    var selectedID: String
    var onSelect: (RuntimeProviderOptionDTO) -> Void

    var body: some View {
        SiftSheetScaffold(title: title, onClose: { dismiss() }) {
            ForEach(providers) { provider in
                Button {
                    onSelect(provider)
                    dismiss()
                } label: {
                    ProviderPickerRow(
                        brandId: provider.id,
                        name: provider.name,
                        description: provider.description,
                        isSelected: provider.id == selectedID
                    )
                }
                .buttonStyle(.plain)
            }
        }
    }
}

private struct WebProviderPickerSheet: View {
    @Environment(\.dismiss) private var dismiss
    var title: String
    var providers: [WebProviderOptionDTO]
    var selectedID: String
    var onSelect: (WebProviderOptionDTO) -> Void

    var body: some View {
        SiftSheetScaffold(title: title, onClose: { dismiss() }) {
            ForEach(providers) { provider in
                Button {
                    onSelect(provider)
                    dismiss()
                } label: {
                    ProviderPickerRow(
                        brandId: provider.id,
                        name: provider.name,
                        description: provider.description,
                        isSelected: provider.id == selectedID
                    )
                }
                .buttonStyle(.plain)
            }
        }
    }
}

/// Dark bottom-sheet container with grab handle, title and close button.
private struct SiftSheetScaffold<Content: View>: View {
    var title: String
    var onClose: () -> Void
    @ViewBuilder var content: Content

    var body: some View {
        ZStack(alignment: .top) {
            Color(hex: 0x131418).ignoresSafeArea()
            VStack(spacing: 0) {
                Capsule()
                    .fill(Color.white.opacity(0.18))
                    .frame(width: 36, height: 5)
                    .padding(.top, 10)

                HStack {
                    Text(title)
                        .font(SiftFont.sans(17, .semibold))
                        .foregroundStyle(SiftColor.textPrimary)
                    Spacer()
                    Button(action: onClose) {
                        Image(systemName: "xmark")
                            .font(.system(size: 13, weight: .semibold))
                            .foregroundStyle(SiftColor.textBody)
                            .frame(width: 30, height: 30)
                            .background(SiftColor.surfaceSoft, in: Circle())
                            .overlay(Circle().strokeBorder(SiftColor.hairline, lineWidth: 1))
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("Close")
                }
                .padding(.horizontal, 20)
                .padding(.top, 14)
                .padding(.bottom, 12)

                ScrollView {
                    VStack(spacing: 8) {
                        content
                    }
                    .padding(.horizontal, 16)
                    .padding(.bottom, 24)
                }
            }
        }
        .presentationBackground(Color(hex: 0x131418))
    }
}

private struct ProviderPickerRow: View {
    var brandId: String
    var name: String
    var description: String
    var isSelected: Bool

    var body: some View {
        HStack(spacing: 12) {
            ProviderBrandMark(providerId: brandId, size: 34)

            VStack(alignment: .leading, spacing: 2) {
                Text(name)
                    .font(SiftFont.sans(15, .medium))
                    .foregroundStyle(SiftColor.textPrimary)
                Text(description)
                    .font(SiftFont.sans(12))
                    .foregroundStyle(isSelected ? SiftColor.accentTextOnWash : SiftColor.textFaint)
                    .lineLimit(1)
            }
            Spacer(minLength: 8)
            if isSelected {
                Image(systemName: "checkmark")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(SiftColor.accent)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 12)
        .padding(.vertical, 11)
        .background(
            isSelected ? SiftColor.accentWash : Color.clear,
            in: RoundedRectangle(cornerRadius: 12, style: .continuous)
        )
        .overlay {
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .strokeBorder(isSelected ? SiftColor.accentBorder : .clear, lineWidth: 1)
        }
    }
}

// MARK: - Grouped settings building blocks

private struct SiftGroupedCard<Content: View>: View {
    @ViewBuilder var content: Content
    var body: some View {
        VStack(spacing: 0) {
            content
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(SiftColor.surface, in: RoundedRectangle(cornerRadius: SiftRadius.group, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: SiftRadius.group, style: .continuous)
                .strokeBorder(SiftColor.hairline, lineWidth: 1)
        }
        .siftCardShadow()
    }
}

private struct SiftGroupDivider: View {
    var body: some View {
        Rectangle()
            .fill(SiftColor.hairlineSoft)
            .frame(height: 1)
            .padding(.leading, 14)
    }
}

private struct SiftSettingRow<Trailing: View>: View {
    var icon: String
    var title: String
    var showsChevron: Bool = true
    @ViewBuilder var trailing: Trailing

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: icon)
                .font(.system(size: 15, weight: .regular))
                .foregroundStyle(SiftColor.textBody)
                .frame(width: 30, height: 30)
                .background(SiftColor.surfaceSoft, in: RoundedRectangle(cornerRadius: 9, style: .continuous))
                .overlay(
                    RoundedRectangle(cornerRadius: 9, style: .continuous)
                        .strokeBorder(SiftColor.hairline, lineWidth: 1)
                )

            Text(title)
                .font(SiftFont.sans(15))
                .foregroundStyle(SiftColor.textPrimary)

            Spacer(minLength: 8)
            trailing
            if showsChevron {
                Image(systemName: "chevron.right")
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(SiftColor.textFaint)
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 14)
        .contentShape(Rectangle())
    }
}

private struct DiagnosticAlert: View {
    var diagnostic: ModelDiagnosticDTO

    private var ok: Bool { diagnostic.ok }

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: ok ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                .font(.system(size: 16, weight: .medium))
                .foregroundStyle(ok ? SiftColor.accent : SiftColor.danger)
                .padding(.top, 1)

            VStack(alignment: .leading, spacing: 4) {
                Text(diagnostic.message)
                    .font(SiftFont.sans(14))
                    .foregroundStyle(SiftColor.textSecondary)
                Text("\(diagnostic.provider) · \(diagnostic.model)")
                    .font(SiftFont.mono(11))
                    .foregroundStyle(ok ? SiftColor.accentTextOnWash : SiftColor.textFaint)
                if let used = diagnostic.webSearchUsed {
                    Text("web search \(used ? "used" : "not used")\(diagnostic.citationCount.map { " · \($0) citations" } ?? "")")
                        .font(SiftFont.mono(11))
                        .foregroundStyle(SiftColor.textFaint)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .background(
            (ok ? SiftColor.accentWash : SiftColor.danger.opacity(0.10)),
            in: RoundedRectangle(cornerRadius: SiftRadius.card, style: .continuous)
        )
        .overlay {
            RoundedRectangle(cornerRadius: SiftRadius.card, style: .continuous)
                .strokeBorder(ok ? SiftColor.accentBorder : SiftColor.danger.opacity(0.25), lineWidth: 1)
        }
    }
}

private enum SiftProfileError: LocalizedError {
    case saveInProgress

    var errorDescription: String? {
        "Provider settings are already being saved."
    }
}

#Preview {
    NavigationStack {
        ProfileView()
    }
    .environment(\.appServices, .preview)
}
