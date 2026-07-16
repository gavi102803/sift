import XCTest
@testable import Sift

final class BackendEndpointTests: XCTestCase {
    private let envURL = URL(string: "https://env.example.com")!
    private let savedURL = URL(string: "https://saved.tailnet.ts.net")!
    private let managedURL = URL(string: "https://managed.sift.app")!
    private let defaultURL = URL(string: "http://127.0.0.1:8000")!

    // MARK: - Resolution priority

    func testEnvOverrideWinsOnEveryBuild() {
        XCTAssertEqual(
            BackendEndpointResolver.resolve(
                envOverride: envURL, savedPersonal: savedURL, managed: managedURL,
                allowsPersonal: true, defaultURL: defaultURL),
            envURL)
        XCTAssertEqual(
            BackendEndpointResolver.resolve(
                envOverride: envURL, savedPersonal: savedURL, managed: managedURL,
                allowsPersonal: false, defaultURL: defaultURL),
            envURL)
    }

    func testSavedPersonalIsSecondOnPersonalBuild() {
        XCTAssertEqual(
            BackendEndpointResolver.resolve(
                envOverride: nil, savedPersonal: savedURL, managed: managedURL,
                allowsPersonal: true, defaultURL: defaultURL),
            savedURL)
    }

    func testDefaultFallbackWhenNoSavedOnPersonalBuild() {
        XCTAssertEqual(
            BackendEndpointResolver.resolve(
                envOverride: nil, savedPersonal: nil, managed: managedURL,
                allowsPersonal: true, defaultURL: defaultURL),
            defaultURL)
    }

    /// Release/Managed: editable Personal URL is ignored; only env > managed > safe failure URL.
    func testReleaseIgnoresSavedAndUsesManaged() {
        XCTAssertEqual(
            BackendEndpointResolver.resolve(
                envOverride: nil, savedPersonal: savedURL, managed: managedURL,
                allowsPersonal: false, defaultURL: defaultURL),
            managedURL)
        XCTAssertEqual(
            BackendEndpointResolver.resolve(
                envOverride: nil, savedPersonal: savedURL, managed: nil,
                allowsPersonal: false, defaultURL: BackendEndpointResolver.missingManagedURL),
            BackendEndpointResolver.missingManagedURL)
    }

    // MARK: - Validation

    func testValidationAcceptsTailnetLocalhostAndHTTPS() {
        for raw in [
            "https://mac.tailnet.ts.net",
            "https://anything.example.com",
            "http://127.0.0.1:8000",
            "http://localhost:8000"
        ] {
            guard case .valid = BackendURLValidation.validate(raw) else {
                return XCTFail("expected valid: \(raw)")
            }
        }
    }

    func testValidationRejectsEmptyHTTPNonLocalAndGarbage() {
        for raw in ["", "   ", "http://example.com", "not a url", "ftp://example.com"] {
            guard case .invalid = BackendURLValidation.validate(raw) else {
                return XCTFail("expected invalid: \(raw)")
            }
        }
    }

    func testValidationTrimsWhitespace() {
        guard case .valid(let url) = BackendURLValidation.validate("  https://mac.ts.net  ") else {
            return XCTFail("expected valid trimmed URL")
        }
        XCTAssertEqual(url.absoluteString, "https://mac.ts.net")
    }

    // MARK: - Personal store round-trip (save / load / reset, no empty override)

    func testStoreSaveLoadReset() {
        let suiteName = "BackendEndpointTests.store"
        let defaults = UserDefaults(suiteName: suiteName)!
        defaults.removePersistentDomain(forName: suiteName)

        XCTAssertNil(PersonalBackendURLStore.savedURL(in: defaults))
        PersonalBackendURLStore.save(savedURL, in: defaults)
        XCTAssertEqual(PersonalBackendURLStore.savedURL(in: defaults), savedURL)
        PersonalBackendURLStore.reset(in: defaults)
        XCTAssertNil(PersonalBackendURLStore.savedURL(in: defaults))

        defaults.removePersistentDomain(forName: suiteName)
    }

    /// An empty stored value never resolves to a URL (so it can't blank-override config).
    func testEmptyStoredValueIsIgnored() {
        let suiteName = "BackendEndpointTests.empty"
        let defaults = UserDefaults(suiteName: suiteName)!
        defaults.set("", forKey: PersonalBackendURLStore.defaultsKey)
        XCTAssertNil(PersonalBackendURLStore.savedURL(in: defaults))
        defaults.removePersistentDomain(forName: suiteName)
    }
}
