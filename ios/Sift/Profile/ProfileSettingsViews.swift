import SwiftUI

// MARK: - Active Model (standard providers)

struct ModelProviderSettingsView: View {
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
                SiftEyebrow(text: "Model")
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

                    if selectedProvider?.requiresApiKey != false {
                        SiftGroupDivider()
                        fieldRow(label: "API Key") {
                            SecureField(apiKeyPlaceholder, text: $apiKey)
                                .textFieldStyle(.plain)
                                .font(SiftFont.mono(13))
                                .foregroundStyle(SiftColor.textSecondary)
                                .tint(SiftColor.accent)
                                .textInputAutocapitalization(.never)
                                .autocorrectionDisabled()
                        }
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
                                        Button(option.id) { model = option.id }
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

                Text("To configure a custom OpenAI-compatible endpoint, use Advanced Connections.")
                    .font(SiftFont.cardDesc)
                    .foregroundStyle(SiftColor.textFaint)
                    .padding(.horizontal, 4)
                    .padding(.top, 2)

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
        .navigationTitle("Active Model")
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
        .sheet(item: $picker) { _ in
            ProviderPickerSheet(
                title: "Select Provider",
                providers: ProviderAllowlist.standardVisible(providers, selected: providerType),
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
        !model.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private func load() async {
        guard !isLoading else { return }
        isLoading = true
        defer { isLoading = false }
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
        defer { isLoadingModels = false }
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
        defer { isSaving = false }
        if !silent { errorMessage = nil }
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

// MARK: - Web search

struct WebSearchSettingsView: View {
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
        .navigationTitle("Research")
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
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
        defer { isLoading = false }
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
        defer { isSaving = false }
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
        providers.filter { $0.id != "disabled" }
    }
}

// MARK: - Advanced Connections (custom endpoint)

struct AdvancedConnectionsView: View {
    @Environment(\.appServices) private var appServices
    @State private var settings: ModelProviderSettingsDTO?
    @State private var baseURL = ""
    @State private var apiKey = ""
    @State private var model = ""
    @State private var errorMessage: String?
    @State private var isLoading = false
    @State private var isSaving = false

    private let customProviderType = "custom"

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                Text("Point Sift at any OpenAI-compatible endpoint. This replaces the active model with your custom connection.")
                    .font(SiftFont.cardDesc)
                    .foregroundStyle(SiftColor.textMuted)
                    .lineSpacing(2)
                    .padding(.horizontal, 4)

                SiftEyebrow(text: "Custom Endpoint")
                    .padding(.top, 2)

                SiftGroupedCard {
                    fieldRow(label: "Base URL") {
                        TextField("", text: $baseURL, prompt: Text("https://…").foregroundColor(SiftColor.textFaint))
                            .textFieldStyle(.plain)
                            .font(SiftFont.mono(13))
                            .foregroundStyle(SiftColor.textSecondary)
                            .tint(SiftColor.accent)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .keyboardType(.URL)
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
                    }
                    SiftGroupDivider()
                    fieldRow(label: "Model") {
                        TextField("", text: $model, prompt: Text("model-id").foregroundColor(SiftColor.textFaint))
                            .textFieldStyle(.plain)
                            .font(SiftFont.mono(13))
                            .foregroundStyle(SiftColor.textSecondary)
                            .tint(SiftColor.accent)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                    }
                }

                SiftButton(
                    title: "Use custom endpoint",
                    systemImage: "checkmark",
                    kind: .primary,
                    isLoading: isSaving
                ) {
                    Task { await save() }
                }
                .disabled(isSaving || !canSave)
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
        .navigationTitle("Advanced Connections")
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
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

    private var apiKeyPlaceholder: String {
        if let preview = settings?.apiKeyPreview, settings?.providerType == customProviderType {
            return "•••••••••••• \(preview)"
        }
        return "API Key"
    }

    private var canSave: Bool {
        !baseURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && !model.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private func load() async {
        guard !isLoading else { return }
        isLoading = true
        defer { isLoading = false }
        errorMessage = nil
        do {
            let current = try await appServices.apiClient.getModelProviderSettings()
            settings = current
            if current.providerType == customProviderType {
                baseURL = current.baseURL
                model = current.explainModel
            }
        } catch is CancellationError {
            return
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func save() async {
        guard !isSaving else { return }
        isSaving = true
        defer { isSaving = false }
        errorMessage = nil
        do {
            let updated = try await appServices.apiClient.updateModelProviderSettings(
                UpdateModelProviderSettingsRequest(
                    providerType: customProviderType,
                    baseURL: baseURL.trimmingCharacters(in: .whitespacesAndNewlines),
                    apiKey: apiKey.isEmpty ? nil : apiKey,
                    explainModel: model.trimmingCharacters(in: .whitespacesAndNewlines),
                    webSearchEnabled: settings?.webSearchEnabled ?? true
                )
            )
            settings = updated
            apiKey = ""
        } catch is CancellationError {
            return
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

// MARK: - Appearance

struct AppearanceSettingsView: View {
    @AppStorage(AppTheme.storageKey) private var themeRaw = AppTheme.system.rawValue

    private var theme: Binding<AppTheme> {
        Binding(
            get: { AppTheme(rawValue: themeRaw) ?? .system },
            set: { themeRaw = $0.rawValue }
        )
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                SiftGroupedCard {
                    SiftSettingRow(icon: "circle.lefthalf.filled", title: "Theme", showsChevron: false) {
                        Picker("", selection: theme) {
                            ForEach(AppTheme.allCases) { option in
                                Text(option.label).tag(option)
                            }
                        }
                        .pickerStyle(.menu)
                        .labelsHidden()
                        .tint(SiftColor.textBody)
                    }
                    SiftGroupDivider()
                    placeholderRow(icon: "textformat.size", title: "Text size")
                    SiftGroupDivider()
                    placeholderRow(icon: "iphone.radiowaves.left.and.right", title: "Haptics")
                }

                Text("Theme follows your device by default. Text size and haptics are on the way.")
                    .font(SiftFont.cardDesc)
                    .foregroundStyle(SiftColor.textFaint)
                    .padding(.horizontal, 4)
                    .padding(.top, 2)
            }
            .padding(.horizontal, 20)
            .padding(.top, 12)
            .padding(.bottom, SiftLayout.tabBarClearance)
        }
        .scrollContentBackground(.hidden)
        .siftScreenBackground()
        .navigationTitle("Appearance")
        .navigationBarTitleDisplayMode(.inline)
    }

    private func placeholderRow(icon: String, title: String) -> some View {
        SiftSettingRow(icon: icon, title: title, showsChevron: false) {
            Text("Coming soon")
                .font(SiftFont.cardDesc)
                .foregroundStyle(SiftColor.textFaint)
        }
        .opacity(0.7)
    }
}

// MARK: - Developer tools (diagnostics, environment, raw config)

struct DeveloperToolsView: View {
    @Environment(\.appServices) private var appServices
    @Environment(CompanionMonitor.self) private var companion: CompanionMonitor?
    @State private var appStatus: AppStatusDTO?
    @State private var modelSettings: ModelProviderSettingsDTO?
    @State private var webSettings: WebProviderSettingsDTO?
    @State private var diagnostic: ModelDiagnosticDTO?
    @State private var webDiagnostic: ModelDiagnosticDTO?
    @State private var errorMessage: String?
    @State private var isTestingModel = false
    @State private var isTestingWeb = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                companionSection
                diagnosticsSection
                environmentSection
                rawConfigSection
                privacyNote
            }
            .padding(.horizontal, 20)
            .padding(.top, 12)
            .padding(.bottom, SiftLayout.tabBarClearance)
        }
        .scrollContentBackground(.hidden)
        .siftScreenBackground()
        .navigationTitle("Developer")
        .navigationBarTitleDisplayMode(.inline)
        .task {
            await companion?.refresh(using: appServices)
            await refresh()
        }
    }

    /// Local companion reachability — the one place mock vs unavailable is shown
    /// explicitly, plus endpoint and the most recent error category (no secrets).
    private var companionSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            SiftEyebrow(text: "Local companion")
            SiftGroupedCard {
                infoRow("Status", value: (companion?.status ?? .unknown).developerLabel)
                SiftGroupDivider()
                infoRow("Endpoint", value: companion?.endpoint ?? appServices.apiClient.backendDescription)
                SiftGroupDivider()
                infoRow("Last error", value: companion?.lastErrorKind?.developerLabel ?? "None")
            }
        }
    }

    private var diagnosticsSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            SiftEyebrow(text: "Diagnostics")
            HStack(spacing: 10) {
                SiftButton(title: "Test model", systemImage: "testtube.2", kind: .primary, height: 44, isLoading: isTestingModel) {
                    Task { await runModelDiagnostic() }
                }
                SiftButton(title: "Web search", systemImage: "globe", kind: .secondary, height: 44, isLoading: isTestingWeb) {
                    Task { await runWebDiagnostic() }
                }
            }
            if let diagnostic { DiagnosticAlert(diagnostic: diagnostic) }
            if let webDiagnostic { DiagnosticAlert(diagnostic: webDiagnostic) }
            if let errorMessage {
                InlineErrorView(message: errorMessage) {
                    Task { await refresh() }
                }
            }
        }
    }

    private var environmentSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            SiftEyebrow(text: "Runtime environment")
            SiftGroupedCard {
                infoRow("Environment", value: appStatus?.env ?? "—")
                SiftGroupDivider()
                infoRow("Backend", value: appServices.apiClient.backendDescription)
                SiftGroupDivider()
                infoRow("Database", value: appStatus?.databaseURL ?? "—")
            }
        }
    }

    private var rawConfigSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            SiftEyebrow(text: "Raw provider configuration")
            SiftGroupedCard {
                infoRow("Model provider", value: modelSettings?.providerType ?? appStatus?.modelProvider ?? "—")
                SiftGroupDivider()
                infoRow("Model", value: modelSettings?.explainModel ?? appStatus?.explainModel ?? "—")
                SiftGroupDivider()
                infoRow("Base URL", value: modelSettings?.baseURL ?? appStatus?.providerBaseURL ?? "—")
                SiftGroupDivider()
                infoRow("API key", value: modelSettings?.apiKeyPreview.map { "•••• \($0)" } ?? "not set")
                SiftGroupDivider()
                infoRow("Web provider", value: webSettings?.providerType ?? "—")
            }
        }
    }

    private var privacyNote: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: "lock")
                .font(.system(size: 15, weight: .regular))
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

    private func infoRow(_ label: String, value: String) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Text(label)
                .font(SiftFont.sans(14))
                .foregroundStyle(SiftColor.textBody)
            Spacer(minLength: 12)
            Text(value)
                .font(SiftFont.mono(12))
                .foregroundStyle(SiftColor.textMuted)
                .multilineTextAlignment(.trailing)
                .lineLimit(2)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 13)
    }

    private func refresh() async {
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
        defer { isTestingModel = false }
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
        defer { isTestingWeb = false }
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
