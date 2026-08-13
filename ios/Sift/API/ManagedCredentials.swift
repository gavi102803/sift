import Foundation
import Security

struct ManagedBetaSession: Codable, Equatable {
    var betaAccessToken: String
    var ownerId: String
    var expiresAt: Date

    func shouldRefresh(now: Date = Date()) -> Bool {
        expiresAt > now && expiresAt.timeIntervalSince(now) <= 7 * 24 * 60 * 60
    }
}

protocol ManagedCredentialStore: AnyObject {
    var installationId: String { get }
    var betaSession: ManagedBetaSession? { get set }
    var providerKey: String? { get set }
    var webProviderKey: String? { get set }
    func clearBetaSession()
}

final class KeychainManagedCredentialStore: ManagedCredentialStore {
    static let shared = KeychainManagedCredentialStore()

    private let service = "app.sift.Sift.managed-beta"

    var installationId: String {
        if let existing = readString(account: "installation-id") {
            return existing
        }
        let created = UUID().uuidString
        write(Data(created.utf8), account: "installation-id")
        return created
    }

    var betaSession: ManagedBetaSession? {
        get {
            guard let data = read(account: "beta-session") else { return nil }
            let decoder = JSONDecoder()
            decoder.dateDecodingStrategy = .iso8601
            return try? decoder.decode(ManagedBetaSession.self, from: data)
        }
        set {
            guard let newValue else {
                delete(account: "beta-session")
                return
            }
            let encoder = JSONEncoder()
            encoder.dateEncodingStrategy = .iso8601
            guard let data = try? encoder.encode(newValue) else { return }
            write(data, account: "beta-session")
        }
    }

    var providerKey: String? {
        get { readString(account: "provider-key") }
        set {
            guard let newValue, !newValue.isEmpty else {
                delete(account: "provider-key")
                return
            }
            write(Data(newValue.utf8), account: "provider-key")
        }
    }

    var webProviderKey: String? {
        get { readString(account: "web-provider-key") }
        set {
            guard let newValue, !newValue.isEmpty else {
                delete(account: "web-provider-key")
                return
            }
            write(Data(newValue.utf8), account: "web-provider-key")
        }
    }

    func clearBetaSession() {
        betaSession = nil
    }

#if DEBUG
    func resetForUITests() {
        delete(account: "installation-id")
        delete(account: "beta-session")
        delete(account: "provider-key")
        delete(account: "web-provider-key")
    }
#endif

    private func readString(account: String) -> String? {
        guard let data = read(account: account) else { return nil }
        return String(data: data, encoding: .utf8)
    }

    private func read(account: String) -> Data? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne
        ]
        var result: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess else {
            return nil
        }
        return result as? Data
    }

    private func write(_ data: Data, account: String) {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account
        ]
        let attributes = [kSecValueData as String: data]
        if SecItemUpdate(query as CFDictionary, attributes as CFDictionary) == errSecItemNotFound {
            var item = query
            item[kSecValueData as String] = data
            SecItemAdd(item as CFDictionary, nil)
        }
    }

    private func delete(account: String) {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account
        ]
        SecItemDelete(query as CFDictionary)
    }
}

final class InMemoryManagedCredentialStore: ManagedCredentialStore {
    let installationId: String
    var betaSession: ManagedBetaSession?
    var providerKey: String?
    var webProviderKey: String?

    init(
        installationId: String = UUID().uuidString,
        betaSession: ManagedBetaSession? = nil,
        providerKey: String? = nil,
        webProviderKey: String? = nil
    ) {
        self.installationId = installationId
        self.betaSession = betaSession
        self.providerKey = providerKey
        self.webProviderKey = webProviderKey
    }

    func clearBetaSession() {
        betaSession = nil
    }
}

actor ManagedSessionController {
    private let credentialStore: any ManagedCredentialStore

    init(credentialStore: any ManagedCredentialStore) {
        self.credentialStore = credentialStore
    }

    func sessionForRequest(baseURL: URL, urlSession: URLSession) async throws -> ManagedBetaSession {
        guard let session = credentialStore.betaSession, session.expiresAt > Date() else {
            credentialStore.clearBetaSession()
            throw SiftAPIError.betaActivationRequired
        }
        guard session.shouldRefresh() else { return session }

        var request = URLRequest(url: baseURL.appending(path: "/v1/beta/session/refresh"))
        request.httpMethod = "POST"
        request.setValue("Bearer \(session.betaAccessToken)", forHTTPHeaderField: "Authorization")
        request.setValue(credentialStore.installationId, forHTTPHeaderField: "X-Sift-Installation")
        let (data, response) = try await urlSession.data(for: request)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw SiftAPIError.invalidResponse
        }
        guard (200..<300).contains(httpResponse.statusCode) else {
            if httpResponse.statusCode == 401 {
                credentialStore.clearBetaSession()
                throw SiftAPIError.betaActivationRequired
            }
            throw SiftAPIError.httpStatus(httpResponse.statusCode, detail: nil)
        }

        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        let refreshed = try decoder.decode(BetaSessionDTO.self, from: data)
        let replacement = ManagedBetaSession(
            betaAccessToken: refreshed.betaAccessToken,
            ownerId: refreshed.ownerId,
            expiresAt: refreshed.expiresAt
        )
        credentialStore.betaSession = replacement
        return replacement
    }

    func clearSession() {
        credentialStore.clearBetaSession()
    }
}

enum ManagedBuild {
    static var isEnabled: Bool {
        if let override = ProcessInfo.processInfo.environment["SIFT_MANAGED_BETA"] {
            return ["1", "true", "yes", "on"].contains(override.lowercased())
        }
        #if DEBUG
        return false
        #else
        return BackendEndpointResolver.managedEndpointURL() != nil
        #endif
    }
}
