import SwiftUI

struct SiftLogo: View {
    var symbolSize: CGFloat = 42
    var showsWordmark = true
    var monochrome = false

    var body: some View {
        HStack(alignment: .center, spacing: 12) {
            SiftSymbol(size: symbolSize, monochrome: monochrome)
            if showsWordmark {
                Text("Sift")
                    .font(.system(size: symbolSize * 0.84, weight: .regular))
                    .foregroundStyle(monochrome ? Color.primary : ink)
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Sift")
    }

    private var ink: Color {
        Color(red: 0.082, green: 0.09, blue: 0.11)
    }
}

struct SiftSymbol: View {
    var size: CGFloat = 56
    var monochrome = false
    var onDark = false

    private var blue: Color {
        monochrome ? ink : Color(red: 0.184, green: 0.42, blue: 1)
    }

    private var ink: Color {
        onDark ? .white : Color(red: 0.082, green: 0.09, blue: 0.11)
    }

    private var quietInk: Color {
        onDark ? Color.white.opacity(0.84) : ink.opacity(0.86)
    }

    var body: some View {
        GeometryReader { proxy in
            let unit = min(proxy.size.width, proxy.size.height) / 100
            ZStack {
                roundedSquare(x: 48, y: 83, size: 17, radius: 4.8, color: blue, unit: unit)

                particle(x: 31, y: 10, size: 3.2, color: blue, shape: .circle, unit: unit)
                particle(x: 49, y: 8, size: 4.2, color: blue, shape: .circle, unit: unit)
                particle(x: 63, y: 15, size: 3.2, color: quietInk, shape: .circle, unit: unit)
                particle(x: 72, y: 23, size: 4.5, rotation: 5, color: blue, shape: .diamond, unit: unit)

                particle(x: 27, y: 23, size: 4.8, color: quietInk, shape: .circle, unit: unit)
                particle(x: 40, y: 25, size: 5.3, color: quietInk, shape: .circle, unit: unit)
                particle(x: 55, y: 30, size: 3.8, color: blue, shape: .circle, unit: unit)
                particle(x: 66, y: 38, size: 3.2, color: quietInk, shape: .circle, unit: unit)

                particle(x: 45, y: 41, size: 7.2, rotation: -14, color: quietInk, shape: .diamond, unit: unit)
                particle(x: 31, y: 49, size: 5.3, rotation: 18, color: blue, shape: .diamond, unit: unit)
                particle(x: 39, y: 58, size: 3.5, color: quietInk, shape: .circle, unit: unit)
                particle(x: 51, y: 61, size: 4.2, color: blue, shape: .circle, unit: unit)

                particle(x: 61, y: 66, size: 3.6, color: quietInk, shape: .circle, unit: unit)
                particle(x: 57, y: 73, size: 3.1, color: blue, shape: .circle, unit: unit)
                particle(x: 48, y: 75, size: 2.8, color: quietInk, shape: .circle, unit: unit)
            }
            .frame(width: proxy.size.width, height: proxy.size.height)
        }
        .frame(width: size, height: size)
        .accessibilityHidden(true)
    }

    private func roundedSquare(
        x: CGFloat,
        y: CGFloat,
        size: CGFloat,
        radius: CGFloat,
        color: Color,
        unit: CGFloat
    ) -> some View {
        RoundedRectangle(cornerRadius: radius * unit)
            .fill(color)
            .frame(width: size * unit, height: size * unit)
            .position(x: x * unit, y: y * unit)
    }

    @ViewBuilder
    private func particle(
        x: CGFloat,
        y: CGFloat,
        size: CGFloat,
        rotation: CGFloat = 0,
        color: Color,
        shape: SiftParticleShape,
        unit: CGFloat
    ) -> some View {
        switch shape {
        case .circle:
            Circle()
                .fill(color)
                .frame(width: size * unit, height: size * unit)
                .position(x: x * unit, y: y * unit)
        case .diamond:
            RoundedRectangle(cornerRadius: 1.6 * unit)
                .fill(color)
                .frame(width: size * unit, height: size * unit)
                .rotationEffect(.degrees(45 + rotation))
                .position(x: x * unit, y: y * unit)
        }
    }
}

private enum SiftParticleShape {
    case circle
    case diamond
}

#Preview {
    VStack(spacing: 24) {
        SiftLogo(symbolSize: 64)
        SiftSymbol(size: 92)
        SiftSymbol(size: 92, monochrome: true)
        SiftSymbol(size: 92, monochrome: true, onDark: true)
            .padding(24)
            .background(Color(red: 0.059, green: 0.067, blue: 0.082))
            .clipShape(RoundedRectangle(cornerRadius: 24))
    }
    .padding()
}
