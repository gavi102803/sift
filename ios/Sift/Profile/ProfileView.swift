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
        List {
            Section {
                profileHeader
            }
            .listRowInsets(EdgeInsets(top: 8, leading: 0, bottom: 8, trailing: 0))
            .listRowBackground(Color.clear)

            Section("Runtime") {
                NavigationLink {
                    ModelProviderSettingsView()
                } label: {
                    SettingsValueRow(
                        title: "Model Provider",
                        value: modelSettings?.providerType ?? appStatus?.modelProvider ?? "Unavailable"
                    )
                }

                NavigationLink {
                    WebSearchSettingsView()
                } label: {
                    SettingsValueRow(
                        title: "Web Search",
                        value: webSettingsLabel
                    )
                }
            }

            Section("Diagnostics") {
                Button {
                    Task {
                        await runModelDiagnostic()
                    }
                } label: {
                    DiagnosticButtonLabel(
                        title: "Test Model",
                        systemImage: "stethoscope",
                        isLoading: isTestingModel
                    )
                }
                .disabled(isTestingModel)

                if let diagnostic {
                    DiagnosticResultRow(diagnostic: diagnostic)
                }

                Button {
                    Task {
                        await runWebDiagnostic()
                    }
                } label: {
                    DiagnosticButtonLabel(
                        title: "Test Web Search",
                        systemImage: "network",
                        isLoading: isTestingWeb
                    )
                }
                .disabled(isTestingWeb)

                if let webDiagnostic {
                    DiagnosticResultRow(diagnostic: webDiagnostic)
                }

                if let errorMessage {
                    InlineErrorView(message: errorMessage) {
                        Task {
                            await refresh()
                        }
                    }
                }
            }

            Section("Privacy") {
                Text("Runtime API keys are stored by Sift Backend and returned to iOS only as a masked preview.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
        }
        .listStyle(.insetGrouped)
        .scrollContentBackground(.hidden)
        .siftScreenBackground()
        .navigationTitle("Profile")
        .refreshable {
            await refresh()
        }
        .task {
            await refresh()
        }
    }

    private var profileHeader: some View {
        HStack(spacing: 14) {
            SiftSymbol(size: 40)
                .frame(width: 46, height: 46)
                .background(Color.white, in: RoundedRectangle(cornerRadius: 12))
                .overlay {
                    RoundedRectangle(cornerRadius: 12)
                        .stroke(SiftTheme.border, lineWidth: 1)
                }

            VStack(alignment: .leading, spacing: 4) {
                Text("Sift User")
                    .font(.headline)
                Text(appStatus?.env ?? "development")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }

            Spacer()
            Image(systemName: "chevron.right")
                .font(.caption.weight(.semibold))
                .foregroundStyle(.tertiary)
        }
        .padding(14)
        .background(SiftTheme.elevatedSurface, in: RoundedRectangle(cornerRadius: SiftTheme.cornerRadius))
        .overlay {
            RoundedRectangle(cornerRadius: SiftTheme.cornerRadius)
                .stroke(SiftTheme.border, lineWidth: 1)
        }
    }

    private var webSettingsLabel: String {
        guard let webSettings else {
            return appStatus?.webSearchEnabled == true ? "On" : "Off"
        }
        return webSettings.webSearchEnabled ? webSettings.providerType : "Off"
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
        List {
            if isLoading {
                Section {
                    HStack {
                        Text("Loading")
                        Spacer()
                        ProgressView()
                    }
                }
            }

            Section("Configuration") {
                Button {
                    picker = ProviderPickerPresentation()
                } label: {
                    SettingsValueRow(
                        title: "Model Provider",
                        value: selectedProvider?.name ?? providerType
                    )
                }
                .buttonStyle(.plain)

                TextField("Base URL", text: $baseURL)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .disabled(selectedProvider?.adapter == "mock")

                SecureField(apiKeyPlaceholder, text: $apiKey)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .disabled(selectedProvider?.requiresApiKey == false)

                HStack {
                    TextField("Model", text: $model)
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
                    }
                    .disabled(providerModels.isEmpty)
                    .accessibilityLabel("Choose model")
                }
            }

            Section {
                Button {
                    Task {
                        await loadModels()
                    }
                } label: {
                    DiagnosticButtonLabel(
                        title: "Load Models",
                        systemImage: "arrow.down.circle",
                        isLoading: isLoadingModels
                    )
                }
                .disabled(isLoadingModels || selectedProvider?.supportsModelListing == false)

                Button {
                    Task {
                        await save()
                    }
                } label: {
                    DiagnosticButtonLabel(
                        title: "Save",
                        systemImage: "checkmark",
                        isLoading: isSaving
                    )
                }
                .disabled(isSaving || !canSave)
            }

            if let errorMessage {
                Section {
                    InlineErrorView(message: errorMessage) {
                        Task {
                            await load()
                        }
                    }
                }
            }
        }
        .navigationTitle("Model Provider")
        .navigationBarTitleDisplayMode(.inline)
        .listStyle(.insetGrouped)
        .scrollContentBackground(.hidden)
        .siftScreenBackground()
        .task {
            await load()
        }
        .sheet(item: $picker) { _ in
            ProviderPickerSheet(
                title: "Model Provider",
                providers: visibleProviders,
                selectedID: providerType
            ) { provider in
                apply(provider)
            }
            .presentationDetents([.medium, .large])
        }
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
            return "API Key (\(preview))"
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
        List {
            Section {
                Toggle("Web Search", isOn: $isEnabled)
            }

            Section("Configuration") {
                Button {
                    picker = WebProviderPickerPresentation()
                } label: {
                    SettingsValueRow(
                        title: "Provider",
                        value: selectedProvider?.name ?? providerType
                    )
                }
                .buttonStyle(.plain)

                if selectedProvider?.requiresApiKey == true {
                    SecureField(apiKeyPlaceholder, text: $apiKey)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                }
            }

            Section {
                Button {
                    Task {
                        await save()
                    }
                } label: {
                    DiagnosticButtonLabel(
                        title: "Save",
                        systemImage: "checkmark",
                        isLoading: isSaving
                    )
                }
                .disabled(isSaving || selectedProvider?.status == "comingSoon")
            }

            if let errorMessage {
                Section {
                    InlineErrorView(message: errorMessage) {
                        Task {
                            await load()
                        }
                    }
                }
            }
        }
        .navigationTitle("Web Search")
        .navigationBarTitleDisplayMode(.inline)
        .listStyle(.insetGrouped)
        .scrollContentBackground(.hidden)
        .siftScreenBackground()
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
        }
    }

    private var selectedProvider: WebProviderOptionDTO? {
        providers.first { $0.id == providerType }
    }

    private var apiKeyPlaceholder: String {
        if let preview = selectedProvider?.apiKeyPreview ?? settings?.apiKeyPreview {
            return "API Key (\(preview))"
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

private struct ProviderPickerSheet: View {
    @Environment(\.dismiss) private var dismiss
    var title: String
    var providers: [RuntimeProviderOptionDTO]
    var selectedID: String
    var onSelect: (RuntimeProviderOptionDTO) -> Void

    var body: some View {
        NavigationStack {
            List(providers) { provider in
                Button {
                    onSelect(provider)
                    dismiss()
                } label: {
                    ProviderOptionRow(
                        title: provider.name,
                        subtitle: provider.description,
                        status: provider.status,
                        isSelected: provider.id == selectedID
                    )
                }
                .buttonStyle(.plain)
            }
            .navigationTitle(title)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") {
                        dismiss()
                    }
                }
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
        NavigationStack {
            List(providers) { provider in
                Button {
                    onSelect(provider)
                    dismiss()
                } label: {
                    ProviderOptionRow(
                        title: provider.name,
                        subtitle: provider.description,
                        status: provider.status,
                        isSelected: provider.id == selectedID
                    )
                }
                .buttonStyle(.plain)
            }
            .navigationTitle(title)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") {
                        dismiss()
                    }
                }
            }
        }
    }
}

private struct SettingsValueRow: View {
    var title: String
    var value: String

    var body: some View {
        HStack {
            Text(title)
            Spacer()
            Text(value)
                .foregroundStyle(.secondary)
        }
    }
}

private struct ProviderOptionRow: View {
    var title: String
    var subtitle: String
    var status: String
    var isSelected: Bool

    var body: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 8) {
                    Text(title)
                    if status != "available" {
                        Text(status)
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                    }
                }
                Text(subtitle)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }
            Spacer()
            if isSelected {
                Image(systemName: "checkmark")
                    .foregroundStyle(.blue)
            }
        }
    }
}

private struct DiagnosticButtonLabel: View {
    var title: String
    var systemImage: String
    var isLoading: Bool

    var body: some View {
        HStack {
            if isLoading {
                ProgressView()
            } else {
                Label(title, systemImage: systemImage)
            }
            Spacer()
        }
    }
}

private struct DiagnosticResultRow: View {
    var diagnostic: ModelDiagnosticDTO

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Label(
                diagnostic.message,
                systemImage: diagnostic.ok ? "checkmark.circle" : "xmark.octagon"
            )
            .foregroundStyle(diagnostic.ok ? .green : .red)

            HStack(spacing: 12) {
                Text("Provider: \(diagnostic.provider)")
                Text("Model: \(diagnostic.model)")
            }
            .foregroundStyle(.secondary)

            if let webSearchUsed = diagnostic.webSearchUsed {
                HStack(spacing: 12) {
                    Text("Web Search Used: \(webSearchUsed ? "Yes" : "No")")
                    if let citationCount = diagnostic.citationCount {
                        Text("Citations: \(citationCount)")
                    }
                }
                .foregroundStyle(webSearchUsed ? .green : .orange)
            }
        }
        .font(.footnote)
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
