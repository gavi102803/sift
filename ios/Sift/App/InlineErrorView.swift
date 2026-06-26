import SwiftUI

struct InlineErrorView: View {
    var message: String
    var retryTitle: String = "Retry"
    var retry: (() -> Void)?

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Label(message, systemImage: "exclamationmark.triangle")
                .font(.footnote)
                .foregroundStyle(.red)

            if let retry {
                Button {
                    retry()
                } label: {
                    Label(retryTitle, systemImage: "arrow.clockwise")
                }
                .font(.footnote.weight(.medium))
                .buttonStyle(.borderless)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(10)
        .background(.red.opacity(0.08), in: RoundedRectangle(cornerRadius: 8))
        .overlay {
            RoundedRectangle(cornerRadius: 8)
                .stroke(.red.opacity(0.2), lineWidth: 1)
        }
    }
}

