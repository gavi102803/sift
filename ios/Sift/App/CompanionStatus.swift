import SwiftUI

/// Local-companion reachability, surfaced honestly without leaking transport
/// detail. The "companion" is the user's local Sift backend (Mac + SQLite +
/// model API). Product mode: iOS → local backend, which can be down while
/// already-captured cards remain readable.
enum CompanionStatus: Equatable {
    case unknown
    case checking
    case available
    case unavailable
    case mock

    /// User-facing label for the Developer surface (never shown in normal UI).
    var developerLabel: String {
        switch self {
        case .unknown: "Unknown"
        case .checking: "Checking…"
        case .available: "Available"
        case .unavailable: "Unavailable"
        case .mock: "Mock (preview data)"
        }
    }
}

/// A sanitized classification of a network / runtime failure. It carries **no**
/// raw error text, URLs, HTTP bodies, status codes as prose, or provider names —
/// only a category, so normal UI can stay honest and quiet.
enum CompanionErrorKind: Equatable {
    case unreachable      // couldn't connect / offline / timed out / host not found
    case companionError   // reached the backend; it returned a server (5xx) error
    case requestRejected  // backend rejected the request (4xx)
    case unknown

    init(_ error: Error) {
        if error is CancellationError {
            self = .unknown
            return
        }
        if let urlError = error as? URLError {
            switch urlError.code {
            case .cannotConnectToHost, .cannotFindHost, .notConnectedToInternet,
                 .timedOut, .networkConnectionLost, .dnsLookupFailed,
                 .secureConnectionFailed:
                self = .unreachable
            default:
                self = .unknown
            }
            return
        }
        if let apiError = error as? SiftAPIError {
            switch apiError {
            case .invalidResponse:
                self = .unknown
            case .httpStatus(let code, _):
                switch code {
                case 500...599: self = .companionError
                case 400...499: self = .requestRejected
                default: self = .unknown
                }
            }
            return
        }
        self = .unknown
    }

    /// Short, secret-free label for the Developer surface only.
    var developerLabel: String {
        switch self {
        case .unreachable: "Unreachable (connection)"
        case .companionError: "Companion error (5xx)"
        case .requestRejected: "Request rejected (4xx)"
        case .unknown: "Unknown error"
        }
    }
}

/// Centralized user-facing copy. Quiet, editorial, never technical.
enum CompanionCopy {
    static let unreachableTitle = "Sift couldn’t reach your local companion."
    static let unreachableBody = "Your question is saved. Try again when it reconnects."

    static let generationTitle = "Sift couldn’t finish that explanation."
    static let generationBody = "Your original question is still here. Try again."

    /// Title/body pair for a blocked user action, chosen by failure category.
    static func message(for kind: CompanionErrorKind) -> (title: String, body: String) {
        switch kind {
        case .unreachable:
            return (unreachableTitle, unreachableBody)
        default:
            return (generationTitle, generationBody)
        }
    }

    /// One-line hint (e.g. under the composer) for a blocked action.
    static func hint(for kind: CompanionErrorKind) -> String {
        let message = message(for: kind)
        return "\(message.title) \(message.body)"
    }

    /// Quiet line shown when reading an already-saved card while offline.
    static let readingOffline = "Showing your saved copy — Sift couldn’t reach your local companion."
}

/// Shared, in-memory reachability state. Optional in the environment so previews
/// and tests don't need to inject it. Never persisted.
@MainActor
@Observable
final class CompanionMonitor {
    private(set) var status: CompanionStatus = .unknown
    private(set) var lastErrorKind: CompanionErrorKind?
    /// Endpoint label for the Developer surface (e.g. the base URL). Not a secret.
    private(set) var endpoint: String = "—"

    init() {}

    func refresh(using services: AppServices) async {
        endpoint = services.apiClient.backendDescription
        if services.usesMockBackend {
            status = .mock
            return
        }
        if status != .available { status = .checking }
        do {
            _ = try await services.apiClient.getAppStatus()
            status = .available
            lastErrorKind = nil
        } catch is CancellationError {
            // leave prior status untouched
        } catch {
            status = .unavailable
            lastErrorKind = CompanionErrorKind(error)
        }
    }

    /// Record a failure from a real user action so Developer can show its
    /// category and so reachability flips when the companion is unreachable.
    func note(_ error: Error) {
        let kind = CompanionErrorKind(error)
        lastErrorKind = kind
        if kind == .unreachable { status = .unavailable }
    }

    func noteSuccess() {
        if status != .mock { status = .available }
        lastErrorKind = nil
    }
}

// MARK: - Quiet inline notice

/// A restrained, non-blocking notice for a blocked network action or an offline
/// read. Deliberately small — there is no persistent banner.
struct CompanionNotice: View {
    enum Tone { case info, warning }

    var text: String
    var tone: Tone = .warning
    var onRetry: (() -> Void)?
    var isRetrying: Bool = false

    private var accent: Color {
        tone == .warning ? SiftColor.danger : SiftColor.textMuted
    }

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: tone == .warning ? "wifi.slash" : "info.circle")
                .font(.system(size: 13, weight: .regular))
                .foregroundStyle(accent)
                .padding(.top, 1)
            Text(text)
                .font(SiftFont.cardDesc)
                .foregroundStyle(SiftColor.textMuted)
                .lineSpacing(2)
                .frame(maxWidth: .infinity, alignment: .leading)
            if let onRetry {
                Button(action: onRetry) {
                    if isRetrying {
                        ProgressView().controlSize(.small)
                    } else {
                        Text("Try again")
                            .font(SiftFont.sans(13, .semibold))
                            .foregroundStyle(SiftColor.accent)
                    }
                }
                .buttonStyle(.plain)
                .disabled(isRetrying)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(SiftColor.surfaceSoft, in: RoundedRectangle(cornerRadius: SiftRadius.card, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: SiftRadius.card, style: .continuous)
                .strokeBorder(SiftColor.hairline, lineWidth: 1)
        )
    }
}

#if DEBUG
#Preview("Companion notices") {
    VStack(alignment: .leading, spacing: 14) {
        CompanionNotice(text: CompanionCopy.readingOffline, tone: .info)
        CompanionNotice(text: CompanionCopy.hint(for: .unreachable), tone: .warning)
        CompanionNotice(
            text: "Sift couldn’t finish that explanation.",
            tone: .warning,
            onRetry: {},
            isRetrying: false
        )
        ForEach([CompanionStatus.available, .unavailable, .mock, .checking], id: \.developerLabel) { status in
            Text("Developer status — \(status.developerLabel)")
                .font(SiftFont.mono(12))
                .foregroundStyle(SiftColor.textMuted)
        }
    }
    .padding(20)
    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
    .siftScreenBackground()
    .preferredColorScheme(.dark)
}
#endif
