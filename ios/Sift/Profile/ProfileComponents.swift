import SwiftUI

// MARK: - Provider visibility (frontend allowlist)

/// iOS-side allowlist of providers safe to surface as user settings. The backend
/// catalog may register many upstream profiles that share an OpenAI-compatible
/// adapter without Sift conformance; we don't expose those here.
enum ProviderAllowlist {
    /// Shown in the standard "Active Model" picker.
    static let standard: Set<String> = [
        "openai", "anthropic", "gemini", "deepseek", "openrouter", "kimi", "nous"
    ]
    /// Shown only under Advanced Connections.
    static let advanced: Set<String> = ["custom"]

    static func isStandardVisible(_ provider: RuntimeProviderOptionDTO) -> Bool {
        provider.id != "mock"
            && provider.status != "comingSoon"
            && standard.contains(provider.id)
    }

    /// Visible providers for the Active Model picker, always including the
    /// currently-selected one so active config is never hidden.
    static func standardVisible(
        _ providers: [RuntimeProviderOptionDTO],
        selected: String
    ) -> [RuntimeProviderOptionDTO] {
        providers
            .filter { isStandardVisible($0) || ($0.id == selected && $0.id != "mock") }
            .sorted { $0.name < $1.name }
    }
}

// MARK: - Provider picker sheets

struct ProviderPickerPresentation: Identifiable {
    let id = UUID()
}

struct WebProviderPickerPresentation: Identifiable {
    let id = UUID()
}

struct ProviderPickerSheet: View {
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

struct WebProviderPickerSheet: View {
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
struct SiftSheetScaffold<Content: View>: View {
    var title: String
    var onClose: () -> Void
    @ViewBuilder var content: Content

    var body: some View {
        ZStack(alignment: .top) {
            SiftColor.canvas.ignoresSafeArea()
            VStack(spacing: 0) {
                Capsule()
                    .fill(Color.primary.opacity(0.2))
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
        .presentationBackground(SiftColor.canvas)
    }
}

struct ProviderPickerRow: View {
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

// MARK: - Diagnostics result (Developer)

struct DiagnosticAlert: View {
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

enum SiftProfileError: LocalizedError {
    case saveInProgress

    var errorDescription: String? {
        "Provider settings are already being saved."
    }
}
