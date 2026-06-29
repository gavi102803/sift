import Foundation

/// Centralized resolution of the backend base URL used by every API request.
///
/// Priority (highest first):
/// 1. `SIFT_BACKEND_BASE_URL` environment override (any build)
/// 2. user-saved **Personal** backend URL — Debug/Personal builds only
///    (the Tailnet dogfood path: iPhone → Tailscale → Mac running the backend)
/// 3. default `http://127.0.0.1:8000` (Debug) / compiled-in managed endpoint (Release)
///
/// Release / Managed (TestFlight) builds never read a user-editable URL.
enum BackendEndpointResolver {
    static let defaultURL = URL(string: "http://127.0.0.1:8000")!

    /// Whether this build lets the user edit a Personal backend URL.
    static var allowsPersonalOverride: Bool {
        #if DEBUG
        true
        #else
        false
        #endif
    }

    /// The base URL every request should use right now. Resolved per call so a
    /// freshly-saved Personal URL takes effect immediately (no app restart).
    static func current() -> URL {
        resolve(
            envOverride: environmentOverrideURL(),
            savedPersonal: PersonalBackendURLStore.savedURL(),
            managed: managedEndpointURL(),
            allowsPersonal: allowsPersonalOverride,
            defaultURL: defaultURL
        )
    }

    /// Pure resolution core (unit-testable; no environment/persistence access).
    static func resolve(
        envOverride: URL?,
        savedPersonal: URL?,
        managed: URL?,
        allowsPersonal: Bool,
        defaultURL: URL
    ) -> URL {
        if let envOverride { return envOverride }
        if allowsPersonal {
            return savedPersonal ?? defaultURL
        }
        return managed ?? defaultURL
    }

    static func environmentOverrideURL() -> URL? {
        normalizedURL(ProcessInfo.processInfo.environment["SIFT_BACKEND_BASE_URL"])
    }

    /// Managed endpoint compiled into Release builds via Info.plist `SIFTBackendBaseURL`.
    static func managedEndpointURL() -> URL? {
        normalizedURL(Bundle.main.object(forInfoDictionaryKey: "SIFTBackendBaseURL") as? String)
    }

    private static func normalizedURL(_ value: String?) -> URL? {
        guard let value, !value.isEmpty, let url = URL(string: value) else { return nil }
        return url
    }
}

/// Persistence for the Personal (Tailnet dogfood) backend URL. The URL is **not**
/// a secret, so `UserDefaults` is acceptable. Only consulted on Debug/Personal builds.
enum PersonalBackendURLStore {
    static let defaultsKey = "siftPersonalBackendURL"

    static func savedURL(in defaults: UserDefaults = .standard) -> URL? {
        guard let raw = defaults.string(forKey: defaultsKey),
              !raw.isEmpty,
              let url = URL(string: raw) else { return nil }
        return url
    }

    static func save(_ url: URL, in defaults: UserDefaults = .standard) {
        defaults.set(url.absoluteString, forKey: defaultsKey)
    }

    static func reset(in defaults: UserDefaults = .standard) {
        defaults.removeObject(forKey: defaultsKey)
    }
}

/// Minimal validation for a user-entered backend URL. Not a network-security
/// policy — just enough to avoid saving garbage or an empty override.
enum BackendURLValidation {
    enum Result: Equatable {
        case valid(URL)
        case invalid(String)
    }

    static func validate(_ raw: String) -> Result {
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            return .invalid("Enter a backend URL.")
        }
        guard let url = URL(string: trimmed),
              let scheme = url.scheme?.lowercased(),
              let host = url.host, !host.isEmpty else {
            return .invalid("That doesn’t look like a valid URL.")
        }
        switch scheme {
        case "https":
            // Covers Tailnet `https://<machine>.<tailnet>.ts.net` and other https hosts.
            return .valid(url)
        case "http" where host == "127.0.0.1" || host == "localhost":
            return .valid(url)
        default:
            return .invalid("Use https://, or http:// only for localhost.")
        }
    }
}
