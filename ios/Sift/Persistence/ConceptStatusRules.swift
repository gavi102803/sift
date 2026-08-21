import Foundation

enum ConceptStatusRules {
    static func isLocalOnly(_ captureStatus: String) -> Bool {
        [
            CaptureStatus.draft.rawValue,
            CaptureStatus.pendingGeneration.rawValue,
            CaptureStatus.generating.rawValue,
            CaptureStatus.buildingCard.rawValue,
            CaptureStatus.needsDisambiguation.rawValue,
            CaptureStatus.generationFailed.rawValue
        ].contains(captureStatus)
    }

    static func canSubmitFollowUp(_ captureStatus: String) -> Bool {
        captureStatus == CaptureStatus.ready.rawValue
    }
}
