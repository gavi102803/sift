import SwiftUI

enum SiftTheme {
    static let cornerRadius: CGFloat = 14
    static let compactRadius: CGFloat = 10

    static var background: Color {
        Color(uiColor: .systemGroupedBackground)
    }

    static var surface: Color {
        Color(uiColor: .secondarySystemGroupedBackground)
    }

    static var elevatedSurface: Color {
        Color(uiColor: .systemBackground)
    }

    static var subtleFill: Color {
        Color(uiColor: .tertiarySystemFill)
    }

    static var accentSoft: Color {
        Color.accentColor.opacity(0.12)
    }

    static var border: Color {
        Color.primary.opacity(0.08)
    }
}

struct SiftScreenBackground: ViewModifier {
    func body(content: Content) -> some View {
        content
            .background(SiftTheme.background.ignoresSafeArea())
    }
}

struct SiftCardStyle: ViewModifier {
    var padding: CGFloat = 14

    func body(content: Content) -> some View {
        content
            .padding(padding)
            .background(SiftTheme.elevatedSurface, in: RoundedRectangle(cornerRadius: SiftTheme.cornerRadius))
            .overlay {
                RoundedRectangle(cornerRadius: SiftTheme.cornerRadius)
                    .stroke(SiftTheme.border, lineWidth: 1)
            }
            .shadow(color: Color.black.opacity(0.04), radius: 10, y: 4)
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

