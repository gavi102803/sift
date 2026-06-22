import SwiftUI

struct AppServices {
    var apiClient: any SiftAPIClient

    static var live: AppServices {
        AppServices(apiClient: SiftAPIClientFactory.makeDefault())
    }

    static var preview: AppServices {
        AppServices(apiClient: MockSiftAPIClient())
    }
}

private struct AppServicesKey: EnvironmentKey {
    static let defaultValue = AppServices.preview
}

extension EnvironmentValues {
    var appServices: AppServices {
        get { self[AppServicesKey.self] }
        set { self[AppServicesKey.self] = newValue }
    }
}

