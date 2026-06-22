# Sift iOS

SwiftUI source scaffold for the Sift iOS app.

This folder contains app, feature, API, and SwiftData source files that can be imported into an Xcode iOS app target named `Sift`.

Current environment note:

- The current workspace does not have Xcode or `xcodebuild`.
- These files are written as normal Swift source, but build validation should happen later on macOS with Xcode.

Recommended Xcode target settings:

- iOS 17+
- SwiftUI app lifecycle
- SwiftData enabled
- Add `MarkdownUI` package when rich answer rendering is wired

Backend configuration:

- Set the `SIFT_BACKEND_BASE_URL` environment variable in the Xcode scheme to call a real backend.
- For iOS Simulator, use the Mac host URL, for example `http://127.0.0.1:8000`.
- For a physical device, use the Mac's LAN address, for example `http://192.168.1.10:8000`.
- Alternatively add an Info.plist string key named `SIFTBackendBaseURL`.
- If no backend URL is configured, the app falls back to `MockSiftAPIClient` for local UI work.
