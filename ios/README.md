# Sift iOS

SwiftUI source scaffold for the Sift iOS app.

This folder contains the Xcode project, app target, feature, API, and SwiftData source files for Sift.

Current environment note:

- This machine has full Xcode available for `xcodebuild`, iOS Simulator, `simctl`, and the iOS Simulator SDK.
- The Xcode project lives at `ios/Sift.xcodeproj`.

Local setup check:

```bash
./scripts/check-ios-dev-env.sh
```

After installing Xcode from the Mac App Store or Apple Developer downloads, run:

```bash
sudo xcode-select -s /Applications/Xcode.app/Contents/Developer
sudo xcodebuild -license accept
xcodebuild -runFirstLaunch
./scripts/check-ios-dev-env.sh
```

Xcode target settings:

- iOS 17+
- SwiftUI app lifecycle
- SwiftData enabled
- Target name: `Sift`
- Unit test target: `SiftTests`
- Bundle identifier: `app.sift.Sift`
- Source files under `ios/Sift`
- Add `MarkdownUI` package when rich answer rendering is wired

Backend configuration:

- Debug builds default to `http://127.0.0.1:8000` for Simulator-friendly local MVP runs.
- Set the `SIFT_BACKEND_BASE_URL` environment variable in the Xcode scheme to override the backend.
- For iOS Simulator, use the Mac host URL, for example `http://127.0.0.1:8000`.
- For a physical device, publish the Mac loopback service with Tailscale Serve
  and save its `https://<mac-machine>.<tailnet>.ts.net` URL in Profile >
  Developer. Do not set a scheme environment override for this path because it
  takes precedence over the saved Personal URL.
- Alternatively add an Info.plist string key named `SIFTBackendBaseURL`.
- SwiftUI previews still use `MockSiftAPIClient` for local UI work.

Validation:

- Run the shared `Sift` scheme tests in Xcode, or use XcodeBuildMCP `test_sim`.
- `SiftTests` currently covers capture failure/retry persistence, manual summary and note edit audit records, failed follow-up recovery drafts, local failed captures surviving remote refresh pruning, organization de-duplication, proposals, relation lifecycle, and Library search matching.
- The Record flow saves a local draft and navigates to its detail immediately; backend generation then updates the card when the model response completes.
- Conversation answers fill incrementally and the final validated response updates
  local concept state. Personal mode reads the backend stream; Managed mode polls
  durable ModelRun events while the request-local BYOK resume executes.
- The Record input supports voice capture through iOS Speech recognition. Simulator microphone behavior can vary; validate dictation on a real device before release.
