//  SiftTheme.suggested.swift
//  Sift — Dark Redesign (xAI canvas + lobe-ui language)
//
//  Direct SwiftUI translation of the Design Tokens in README.md.
//  Reconcile with the existing ios/Sift/App/SiftTheme.swift — keep your existing
//  API surface where it already exists; adopt the values below.

import SwiftUI

// MARK: - Color tokens

extension Color {
    init(hex: UInt32, alpha: Double = 1) {
        self.init(
            .sRGB,
            red:   Double((hex >> 16) & 0xFF) / 255,
            green: Double((hex >> 8)  & 0xFF) / 255,
            blue:  Double( hex        & 0xFF) / 255,
            opacity: alpha
        )
    }
}

enum SiftColor {
    static let canvas        = Color(hex: 0x0A0B0D)   // app background, every screen
    static let surface       = Color(hex: 0x16181C)   // block cards, grouped setting cards
    static let surfaceSoft    = Color.white.opacity(0.05) // fields, chips, secondary buttons
    static let surfaceSoftHi  = Color.white.opacity(0.07) // active tab pill, user bubble
    static let hairline       = Color.white.opacity(0.07) // card borders, dividers
    static let hairlineSoft   = Color.white.opacity(0.06) // inner dividers

    static let accent         = Color(hex: 0x3D7FFF)   // the single accent
    static let accentWash     = Color(hex: 0x3D7FFF, alpha: 0.12)
    static let accentBorder   = Color(hex: 0x3D7FFF, alpha: 0.20)
    static let accentTextOnWash = Color(hex: 0x9CC0FF)

    static let textPrimary   = Color(hex: 0xF3F4F5)
    static let textSecondary = Color(hex: 0xC7CACE)
    static let textBody      = Color(hex: 0xABAFB6)
    static let textMuted     = Color(hex: 0x8B8F96)
    static let textFaint     = Color(hex: 0x74787E)
    static let textFaintest  = Color(hex: 0x5B5E63)
}

// MARK: - Radii

enum SiftRadius {
    static let card: CGFloat   = 16
    static let group: CGFloat  = 16
    static let tile: CGFloat   = 12   // icon tiles 10–14
    static let button: CGFloat = 13
    static let field: CGFloat  = 14
    static let chip: CGFloat   = 8
    static let tabBar: CGFloat = 26
    static let tabItem: CGFloat = 20
    static let sheetTop: CGFloat = 26
    static let send: CGFloat   = 12   // rounded square, not a circle
}

// MARK: - Typography ramp
//  Geist if bundled, else SF Pro. Mono = Geist Mono else SF Mono.

enum SiftFont {
    static func sans(_ size: CGFloat, _ weight: Font.Weight = .regular) -> Font {
        .system(size: size, weight: weight)        // swap to .custom("Geist-…") if bundled
    }
    static func mono(_ size: CGFloat, _ weight: Font.Weight = .regular) -> Font {
        .system(size: size, weight: weight, design: .monospaced)
    }

    static let screenTitle = sans(30, .bold)        // tracking -0.8
    static let hero        = sans(26, .semibold)    // tracking -0.5
    static let pageTitle   = sans(27, .bold)        // tracking -0.6
    static let navTitle    = sans(16, .semibold)    // tracking -0.3
    static let cardTitle   = sans(15, .semibold)
    static let body        = sans(15)               // line-height ~24
    static let cardDesc    = sans(13)
    static let tag         = sans(11)
    static let tabLabel    = sans(10, .medium)
    static let eyebrow     = mono(11)               // CAPS, tracking +0.6, textFaint
    static let fieldLabel  = mono(10)               // CAPS, tracking +0.5, textFaintest
}

// MARK: - Shadows

extension View {
    /// Block-card elevation (hairline border carries most of it).
    func siftCardShadow() -> some View {
        self
            .shadow(color: .black.opacity(0.5), radius: 1,  x: 0, y: 1)
            .shadow(color: .black.opacity(0.5), radius: 8,  x: 0, y: 6)
    }
    func siftTabBarShadow() -> some View {
        shadow(color: .black.opacity(0.7), radius: 17, x: 0, y: 10)
    }
    func siftPrimaryGlow() -> some View {
        shadow(color: SiftColor.accent.opacity(0.7), radius: 9, x: 0, y: 6)
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
    var body: some View {
        RoundedRectangle(cornerRadius: SiftRadius.tile, style: .continuous)
            .fill(accent ? SiftColor.accentWash : SiftColor.surfaceSoft)
            .overlay(
                RoundedRectangle(cornerRadius: SiftRadius.tile, style: .continuous)
                    .strokeBorder(accent ? SiftColor.accentBorder : SiftColor.hairline, lineWidth: 1)
            )
            .frame(width: size, height: size)
            .overlay(
                Image(systemName: systemName)
                    .font(.system(size: size * 0.5, weight: .regular))
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
            .padding(.horizontal, 9).padding(.vertical, 3)
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
    var body: some View {
        Text(text.uppercased())
            .font(SiftFont.eyebrow)
            .tracking(0.6)
            .foregroundStyle(SiftColor.textFaint)
    }
}

enum SiftButtonKind { case primary, secondary }

/// Primary (accent) / secondary (soft) button.
struct SiftButton: View {
    let title: String
    var systemImage: String? = nil
    var kind: SiftButtonKind = .primary
    var height: CGFloat = 48
    var action: () -> Void = {}
    var body: some View {
        Button(action: action) {
            HStack(spacing: 9) {
                if let s = systemImage { Image(systemName: s) }
                Text(title).font(SiftFont.sans(15, kind == .primary ? .semibold : .medium))
            }
            .frame(maxWidth: .infinity).frame(height: height)
            .foregroundStyle(kind == .primary ? .white : SiftColor.textSecondary)
            .background(
                Group {
                    if kind == .primary { SiftColor.accent }
                    else { SiftColor.surfaceSoft }
                },
                in: RoundedRectangle(cornerRadius: SiftRadius.button, style: .continuous)
            )
            .overlay(
                RoundedRectangle(cornerRadius: SiftRadius.button, style: .continuous)
                    .strokeBorder(kind == .secondary ? Color.white.opacity(0.10) : .clear, lineWidth: 1)
            )
        }
        .modifier(SiftConditionalGlow(on: kind == .primary && height >= 48))
    }
}

private struct SiftConditionalGlow: ViewModifier {
    let on: Bool
    func body(content: Content) -> some View { on ? AnyView(content.siftPrimaryGlow()) : AnyView(content) }
}
