import SwiftUI

struct ManagedBetaOnboardingView: View {
    let apiClient: any SiftAPIClient
    let onComplete: () -> Void

    @State private var inviteCode = ""
    @State private var providers: [RuntimeProviderOptionDTO] = []
    @State private var providerId = "openai"
    @State private var baseURL = "https://api.openai.com/v1"
    @State private var model = "gpt-5.5"
    @State private var apiKey = ""
    @State private var isActivated = false
    @State private var isWorking = false
    @State private var errorMessage: String?

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                    SiftSymbol(size: 42)
                        .padding(.bottom, 4)

                    Text(isActivated ? "Connect your AI" : "Activate Sift Beta")
                        .font(SiftFont.screenTitle)
                        .foregroundStyle(SiftColor.textPrimary)

                    Text(
                        isActivated
                            ? "Your API key stays in this device’s Keychain and is sent only when Sift needs your provider."
                            : "Enter the invite code you received. Sift will bind beta access to this installation."
                    )
                    .font(SiftFont.body)
                    .foregroundStyle(SiftColor.textMuted)
                    .lineSpacing(3)

                    if isActivated {
                        providerForm
                    } else {
                        activationForm
                    }

                    if let errorMessage {
                        InlineErrorView(message: errorMessage) {}
                    }
                }
                .padding(24)
                .frame(maxWidth: 560)
                .frame(maxWidth: .infinity)
            }
            .siftScreenBackground()
            .task { await resumeIfPossible() }
        }
    }

    private var activationForm: some View {
        VStack(spacing: 16) {
            TextField("Invite code", text: $inviteCode)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .textFieldStyle(.roundedBorder)
                .accessibilityIdentifier("managed.inviteCode")

            SiftButton(
                title: "Activate beta access",
                systemImage: "checkmark.seal",
                kind: .primary,
                isLoading: isWorking
            ) {
                Task { await activate() }
            }
            .disabled(isWorking || inviteCode.trimmingCharacters(in: .whitespaces).isEmpty)
            .accessibilityIdentifier("managed.activate")
        }
    }

    private var providerForm: some View {
        VStack(spacing: 14) {
            SiftGroupedCard {
                VStack(alignment: .leading, spacing: 8) {
                    Text("PROVIDER")
                        .font(SiftFont.fieldLabel)
                        .foregroundStyle(SiftColor.textFaintest)
                    Picker("Provider", selection: $providerId) {
                        ForEach(visibleProviders) { provider in
                            Text(provider.name).tag(provider.id)
                        }
                    }
                    .pickerStyle(.menu)
                    .onChange(of: providerId) { _, selected in
                        guard let provider = providers.first(where: { $0.id == selected }) else {
                            return
                        }
                        baseURL = provider.defaultBaseURL
                        model = provider.defaultModel
                    }
                }
                .padding(14)

                SiftGroupDivider()

                onboardingField("MODEL") {
                    TextField("Model", text: $model)
                }

                SiftGroupDivider()

                onboardingField("API KEY") {
                    SecureField("Provider API key", text: $apiKey)
                        .accessibilityIdentifier("managed.providerKey")
                }
            }

            SiftButton(
                title: "Test connection and continue",
                systemImage: "arrow.right",
                kind: .primary,
                isLoading: isWorking
            ) {
                Task { await connectProvider() }
            }
            .disabled(isWorking || model.isEmpty || apiKey.isEmpty)
            .accessibilityIdentifier("managed.connect")
        }
    }

    private var visibleProviders: [RuntimeProviderOptionDTO] {
        providers.filter {
            $0.status == "available" && $0.id != "mock" && $0.exposureTier != "hidden"
        }
    }

    private func onboardingField<Content: View>(
        _ label: String,
        @ViewBuilder content: () -> Content
    ) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(label)
                .font(SiftFont.fieldLabel)
                .foregroundStyle(SiftColor.textFaintest)
            content()
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
        }
        .padding(14)
    }

    private func resumeIfPossible() async {
        guard apiClient.hasBetaSession else { return }
        isActivated = true
        await loadProviders()
        if let settings = try? await apiClient.getModelProviderSettings(),
           settings.apiKeyConfigured {
            onComplete()
        }
    }

    private func activate() async {
        guard !isWorking else { return }
        isWorking = true
        defer { isWorking = false }
        errorMessage = nil
        do {
            try await apiClient.activateBeta(
                inviteCode: inviteCode.trimmingCharacters(in: .whitespacesAndNewlines)
            )
            isActivated = true
            await loadProviders()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func loadProviders() async {
        do {
            providers = try await apiClient.listRuntimeModelProviders().providers
            if let selected = visibleProviders.first(where: { $0.id == providerId })
                ?? visibleProviders.first {
                providerId = selected.id
                baseURL = selected.defaultBaseURL
                model = selected.defaultModel
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func connectProvider() async {
        guard !isWorking else { return }
        isWorking = true
        defer { isWorking = false }
        errorMessage = nil
        do {
            _ = try await apiClient.updateModelProviderSettings(
                UpdateModelProviderSettingsRequest(
                    providerType: providerId,
                    baseURL: baseURL,
                    apiKey: apiKey,
                    explainModel: model,
                    webSearchEnabled: true
                )
            )
            apiKey = ""
            onComplete()
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
