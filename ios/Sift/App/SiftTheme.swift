import SwiftUI
import UIKit

// MARK: - Hex + adaptive helpers

extension Color {
    init(hex: UInt32, alpha: Double = 1) {
        self.init(
            .sRGB,
            red: Double((hex >> 16) & 0xFF) / 255,
            green: Double((hex >> 8) & 0xFF) / 255,
            blue: Double(hex & 0xFF) / 255,
            opacity: alpha
        )
    }

    /// Resolves `light` in light mode and `dark` in dark mode, so a single token
    /// adapts to the active appearance (and Light / Dark / System theme).
    static func adaptive(light: Color, dark: Color) -> Color {
        Color(uiColor: UIColor { traits in
            traits.userInterfaceStyle == .dark ? UIColor(dark) : UIColor(light)
        })
    }
}

// MARK: - Color tokens (appearance-adaptive)

enum SiftColor {
    static let canvas = Color.adaptive(light: Color(hex: 0xF4F5F7), dark: Color(hex: 0x0A0B0D))     // app background
    static let surface = Color.adaptive(light: Color(hex: 0xFFFFFF), dark: Color(hex: 0x16181C))    // cards, grouped rows
    static let surfaceSoft = Color.adaptive(light: Color.black.opacity(0.04), dark: Color.white.opacity(0.05))
    static let surfaceSoftHi = Color.adaptive(light: Color.black.opacity(0.06), dark: Color.white.opacity(0.07))
    static let hairline = Color.adaptive(light: Color.black.opacity(0.10), dark: Color.white.opacity(0.07))
    static let hairlineSoft = Color.adaptive(light: Color.black.opacity(0.07), dark: Color.white.opacity(0.06))

    static let accent = Color(hex: 0x3D7FFF)            // the single accent (both modes)
    static let accentWash = Color.adaptive(light: Color(hex: 0x3D7FFF, alpha: 0.10), dark: Color(hex: 0x3D7FFF, alpha: 0.12))
    static let accentBorder = Color.adaptive(light: Color(hex: 0x3D7FFF, alpha: 0.25), dark: Color(hex: 0x3D7FFF, alpha: 0.20))
    static let accentTextOnWash = Color.adaptive(light: Color(hex: 0x2D63D6), dark: Color(hex: 0x9CC0FF))

    static let textPrimary = Color.adaptive(light: Color(hex: 0x15171A), dark: Color(hex: 0xF3F4F5))
    static let textSecondary = Color.adaptive(light: Color(hex: 0x33363B), dark: Color(hex: 0xC7CACE))
    static let textBody = Color.adaptive(light: Color(hex: 0x52555B), dark: Color(hex: 0xABAFB6))
    static let textMuted = Color.adaptive(light: Color(hex: 0x6C7077), dark: Color(hex: 0x8B8F96))
    static let textFaint = Color.adaptive(light: Color(hex: 0x8A8E95), dark: Color(hex: 0x74787E))
    static let textFaintest = Color.adaptive(light: Color(hex: 0xAAAEB4), dark: Color(hex: 0x5B5E63))

    static let danger = Color.adaptive(light: Color(hex: 0xE5484D), dark: Color(hex: 0xFF6B6B))
}

// MARK: - Appearance preference

/// User-selectable theme. `system` follows the device appearance.
enum AppTheme: String, CaseIterable, Identifiable {
    case system
    case light
    case dark

    var id: String { rawValue }

    var label: String {
        switch self {
        case .system: "System"
        case .light: "Light"
        case .dark: "Dark"
        }
    }

    /// The scheme to force, or nil to follow the system.
    var colorScheme: ColorScheme? {
        switch self {
        case .system: nil
        case .light: .light
        case .dark: .dark
        }
    }

    /// Shared persistence key for `@AppStorage`.
    static let storageKey = "siftTheme"
}

// MARK: - Radii

enum SiftRadius {
    static let card: CGFloat = 16
    static let group: CGFloat = 16
    static let tile: CGFloat = 12
    static let button: CGFloat = 13
    static let field: CGFloat = 14
    static let chip: CGFloat = 8
    static let tabBar: CGFloat = 26
    static let tabItem: CGFloat = 20
    static let sheetTop: CGFloat = 26
    static let send: CGFloat = 12
}

// MARK: - Typography ramp (SF Pro / SF Mono)

enum SiftFont {
    static func sans(_ size: CGFloat, _ weight: Font.Weight = .regular) -> Font {
        .system(size: size, weight: weight)
    }
    static func mono(_ size: CGFloat, _ weight: Font.Weight = .regular) -> Font {
        .system(size: size, weight: weight, design: .monospaced)
    }

    static let screenTitle = sans(30, .bold)
    static let hero = sans(26, .semibold)
    static let pageTitle = sans(27, .bold)
    static let navTitle = sans(16, .semibold)
    static let cardTitle = sans(15, .semibold)
    static let body = sans(15)
    static let cardDesc = sans(13)
    static let tag = sans(11)
    static let tabLabel = sans(10, .medium)
    static let eyebrow = mono(11)
    static let fieldLabel = mono(10)
}

// MARK: - Shadows / elevation

extension View {
    // Shadows are tuned per appearance: deep on dark (separates same-ish darks),
    // but very soft on light so white cards don't float with a hazy halo.
    func siftCardShadow() -> some View {
        self
            .shadow(color: .adaptive(light: .black.opacity(0.04), dark: .black.opacity(0.5)), radius: 1, x: 0, y: 1)
            .shadow(color: .adaptive(light: .black.opacity(0.05), dark: .black.opacity(0.5)), radius: 8, x: 0, y: 6)
    }
    func siftTabBarShadow() -> some View {
        shadow(color: .adaptive(light: .black.opacity(0.10), dark: .black.opacity(0.7)), radius: 17, x: 0, y: 10)
    }
    func siftPrimaryGlow() -> some View {
        shadow(color: SiftColor.accent.opacity(0.7), radius: 9, x: 0, y: 6)
    }
}

// MARK: - Legacy SiftTheme surface (kept so existing call sites compile)

enum SiftTheme {
    static let cornerRadius: CGFloat = SiftRadius.card
    static let compactRadius: CGFloat = SiftRadius.tile

    static var background: Color { SiftColor.canvas }
    static var surface: Color { SiftColor.surface }
    static var elevatedSurface: Color { SiftColor.surface }
    static var subtleFill: Color { SiftColor.surfaceSoft }
    static var accentSoft: Color { SiftColor.accentWash }
    static var border: Color { SiftColor.hairline }
    static var accent: Color { SiftColor.accent }
}

struct SiftScreenBackground: ViewModifier {
    func body(content: Content) -> some View {
        content
            .background(SiftColor.canvas.ignoresSafeArea())
    }
}

struct SiftCardStyle: ViewModifier {
    var padding: CGFloat = 14

    func body(content: Content) -> some View {
        content
            .padding(padding)
            .background(SiftColor.surface, in: RoundedRectangle(cornerRadius: SiftRadius.card, style: .continuous))
            .overlay {
                RoundedRectangle(cornerRadius: SiftRadius.card, style: .continuous)
                    .strokeBorder(SiftColor.hairline, lineWidth: 1)
            }
            .siftCardShadow()
    }
}

extension View {
    func siftScreenBackground() -> some View {
        modifier(SiftScreenBackground())
    }

    func siftCard(padding: CGFloat = 14) -> some View {
        modifier(SiftCardStyle(padding: padding))
    }
}

// MARK: - Reusable building blocks

/// The universal rounded "block" card: surface fill + hairline + card shadow.
struct SiftBlock<Content: View>: View {
    var padding: CGFloat = 14
    @ViewBuilder var content: Content
    var body: some View {
        content
            .padding(padding)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(SiftColor.surface, in: RoundedRectangle(cornerRadius: SiftRadius.card, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: SiftRadius.card, style: .continuous)
                    .strokeBorder(SiftColor.hairline, lineWidth: 1)
            )
            .siftCardShadow()
    }
}

/// Rounded-square glyph tile. Accent variant = focused/primary; neutral = default.
struct SiftIconTile: View {
    let systemName: String
    var accent: Bool = false
    var size: CGFloat = 38
    var radius: CGFloat = SiftRadius.tile
    var body: some View {
        RoundedRectangle(cornerRadius: radius, style: .continuous)
            .fill(accent ? SiftColor.accentWash : SiftColor.surfaceSoft)
            .overlay(
                RoundedRectangle(cornerRadius: radius, style: .continuous)
                    .strokeBorder(accent ? SiftColor.accentBorder : SiftColor.hairline, lineWidth: 1)
            )
            .frame(width: size, height: size)
            .overlay(
                Image(systemName: systemName)
                    .font(.system(size: size * 0.46, weight: .medium))
                    .foregroundStyle(accent ? SiftColor.accent : SiftColor.textBody)
            )
    }
}

/// Tag / select chip.
struct SiftChip: View {
    let text: String
    var selected: Bool = false
    var body: some View {
        Text(text)
            .font(SiftFont.tag)
            .foregroundStyle(selected ? .white : SiftColor.textBody)
            .lineLimit(1)
            .padding(.horizontal, 9).padding(.vertical, 4)
            .background(selected ? SiftColor.accent : SiftColor.surfaceSoft,
                        in: RoundedRectangle(cornerRadius: SiftRadius.chip, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: SiftRadius.chip, style: .continuous)
                    .strokeBorder(selected ? .clear : SiftColor.hairline, lineWidth: 1)
            )
    }
}

/// Mono ALL-CAPS section eyebrow (e.g. RUNTIME, ALL CONCEPTS).
struct SiftEyebrow: View {
    let text: String
    var trailing: String? = nil
    var body: some View {
        HStack(spacing: 8) {
            Text(text.uppercased())
                .font(SiftFont.eyebrow)
                .tracking(0.6)
                .foregroundStyle(SiftColor.textFaint)
            if let trailing {
                Text(trailing)
                    .font(SiftFont.eyebrow)
                    .tracking(0.6)
                    .foregroundStyle(SiftColor.textFaintest)
            }
        }
    }
}

enum SiftButtonKind { case primary, secondary }

/// Primary (accent) / secondary (soft) button.
struct SiftButton: View {
    let title: String
    var systemImage: String? = nil
    var kind: SiftButtonKind = .primary
    var height: CGFloat = 48
    var isLoading: Bool = false
    var action: () -> Void = {}
    var body: some View {
        Button(action: action) {
            HStack(spacing: 9) {
                if isLoading {
                    ProgressView()
                        .tint(kind == .primary ? .white : SiftColor.textSecondary)
                } else {
                    if let systemImage { Image(systemName: systemImage) }
                    Text(title).font(SiftFont.sans(15, kind == .primary ? .semibold : .medium))
                }
            }
            .frame(maxWidth: .infinity).frame(height: height)
            .foregroundStyle(kind == .primary ? .white : SiftColor.textSecondary)
            .background(
                kind == .primary ? SiftColor.accent : SiftColor.surfaceSoft,
                in: RoundedRectangle(cornerRadius: SiftRadius.button, style: .continuous)
            )
            .overlay(
                RoundedRectangle(cornerRadius: SiftRadius.button, style: .continuous)
                    .strokeBorder(kind == .secondary ? Color.white.opacity(0.10) : .clear, lineWidth: 1)
            )
        }
        .buttonStyle(.plain)
        .modifier(SiftConditionalGlow(on: kind == .primary && height >= 48))
    }
}

private struct SiftConditionalGlow: ViewModifier {
    let on: Bool
    func body(content: Content) -> some View { on ? AnyView(content.siftPrimaryGlow()) : AnyView(content) }
}

// MARK: - Grouped settings building blocks (shared by Profile + ConceptDetail)

/// A rounded "grouped" container (iOS Settings style): surface fill + hairline.
/// Rows inside are separated with `SiftGroupDivider`.
struct SiftGroupedCard<Content: View>: View {
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

/// Hairline divider inset to align with row content (used between grouped rows).
struct SiftGroupDivider: View {
    var body: some View {
        Rectangle()
            .fill(SiftColor.hairlineSoft)
            .frame(height: 1)
            .padding(.leading, 14)
    }
}

/// A single settings row: glyph tile + title + trailing value (+ optional chevron).
struct SiftSettingRow<Trailing: View>: View {
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

extension SiftSettingRow where Trailing == EmptyView {
    init(icon: String, title: String, showsChevron: Bool = true) {
        self.icon = icon
        self.title = title
        self.showsChevron = showsChevron
        self.trailing = EmptyView()
    }
}

// MARK: - Provider brand mark

/// A provider brand logo on a white rounded chip, keyed by provider id.
/// Falls back to a globe glyph for unknown providers.
struct ProviderBrandMark: View {
    let providerId: String
    var size: CGFloat = 34
    var cornerRadius: CGFloat = 9

    private var assetName: String? {
        switch providerId.lowercased() {
        case "openai": return "brand-openai"
        case "anthropic", "anthropic_messages": return "brand-anthropic"
        case "gemini": return "brand-gemini"
        case "deepseek": return "brand-deepseek"
        case "openrouter": return "brand-openrouter"
        case "kimi", "kimi-coding": return "brand-kimi"
        case "nous": return "brand-nous"
        case "alibaba", "alibaba-coding-plan", "dashscope", "alibabacloud": return "brand-alibabacloud"
        case "arcee": return "brand-arcee"
        case "gmi", "gmicloud": return "brand-gmicloud"
        case "huggingface": return "brand-huggingface"
        case "nvidia": return "brand-nvidia"
        case "ollama-cloud", "ollama": return "brand-ollama"
        case "minimax": return "brand-minimax"
        case "stepfun": return "brand-stepfun"
        case "novita": return "brand-novita"
        case "zai": return "brand-zai"
        case "azure-foundry", "azure": return "brand-azure"
        case "kilocode": return "brand-kilocode"
        default: return nil
        }
    }

    var body: some View {
        RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
            .fill(.white)
            .frame(width: size, height: size)
            .overlay {
                if let assetName {
                    Image(assetName)
                        .resizable()
                        .aspectRatio(contentMode: .fit)
                        .frame(width: size * 0.62, height: size * 0.62)
                } else {
                    Image(systemName: "globe")
                        .font(.system(size: size * 0.46, weight: .medium))
                        .foregroundStyle(SiftColor.canvas)
                }
            }
            .overlay(
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .strokeBorder(.black.opacity(0.06), lineWidth: 1)
            )
    }
}
