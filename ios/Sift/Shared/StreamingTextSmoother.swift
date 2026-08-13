import Foundation

/// Converts irregular network deltas into small, evenly paced presentation
/// updates. The transport remains truly streaming; this only smooths how text
/// is revealed after each upstream delta arrives.
@MainActor
final class StreamingTextSmoother {
    typealias Sleeper = @Sendable (Duration) async throws -> Void
    typealias FragmentHandler = (String) -> Void

    private let charactersPerTick: Int
    private let tickInterval: Duration
    private let sleeper: Sleeper
    private let onFragment: FragmentHandler
    private var pendingText = ""
    private var drainTask: Task<Void, Error>?
    private var hasEmitted = false

    init(
        charactersPerTick: Int = 6,
        tickInterval: Duration = .milliseconds(24),
        sleeper: @escaping Sleeper = { duration in
            try await Task.sleep(for: duration)
        },
        onFragment: @escaping FragmentHandler
    ) {
        self.charactersPerTick = max(1, charactersPerTick)
        self.tickInterval = tickInterval
        self.sleeper = sleeper
        self.onFragment = onFragment
    }

    /// Buffers an upstream delta without waiting for presentation pacing. This
    /// keeps URLSession/NDJSON consumption independent from UI animation.
    func append(_ delta: String) {
        guard !delta.isEmpty else { return }
        pendingText.append(delta)
        guard drainTask == nil else { return }

        drainTask = Task { @MainActor [weak self] in
            guard let self else { return }
            try await self.drain()
        }
    }

    /// Waits until every accepted character has been presented. Call this
    /// before applying the authoritative terminal payload so it cannot appear
    /// as a final visual jump.
    func finish() async throws {
        while let drainTask {
            try await drainTask.value
        }
    }

    func cancel() {
        pendingText = ""
        drainTask?.cancel()
        drainTask = nil
    }

    private func drain() async throws {
        defer { drainTask = nil }

        while !pendingText.isEmpty {
            if hasEmitted {
                try await sleeper(tickInterval)
            }
            try Task.checkCancellation()
            let end = pendingText.index(
                pendingText.startIndex,
                offsetBy: charactersPerTick,
                limitedBy: pendingText.endIndex
            ) ?? pendingText.endIndex
            let fragment = String(pendingText[..<end])
            pendingText.removeSubrange(..<end)
            onFragment(fragment)
            hasEmitted = true
        }
    }
}
