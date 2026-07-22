import Foundation

@MainActor
struct ConceptMaintenanceObserver {
    let apiClient: any SiftAPIClient

    func observe(
        runIds: [UUID],
        onProgress: (ModelRunDTO, Int) throws -> Void
    ) async throws {
        for runId in runIds {
            var run = try await apiClient.getModelRun(id: runId)
            var lastSequence = 0

            while true {
                try Task.checkCancellation()
                if run.status == "waitingForCredential" {
                    run = try await apiClient.resumeModelRun(id: run.id)
                }

                let events = try await apiClient.listModelRunEvents(
                    id: run.id,
                    afterSequence: lastSequence
                )
                lastSequence = events.reduce(lastSequence) { current, event in
                    max(current, event.sequence)
                }
                try onProgress(run, lastSequence)

                guard Self.activeStatuses.contains(run.status) else { break }
                try await Task.sleep(for: .milliseconds(250))
                run = try await apiClient.getModelRun(id: run.id)
            }
        }
    }

    private static let activeStatuses = Set(["queued", "running", "waitingForCredential"])
}
