import AVFAudio
import AVFoundation
import Combine
import Foundation
import Speech

@MainActor
final class SpeechCaptureService: ObservableObject {
    @Published private(set) var isRecording = false

    private var audioEngine = AVAudioEngine()
    private var recognitionRequest: SFSpeechAudioBufferRecognitionRequest?
    private var recognitionTask: SFSpeechRecognitionTask?
    private let speechRecognizer = SFSpeechRecognizer()

    func start(onTranscript: @escaping @MainActor (String) -> Void) async throws {
        guard !isRecording else { return }
        try await requestPermissions()
        guard let speechRecognizer, speechRecognizer.isAvailable else {
            throw SpeechCaptureError.recognizerUnavailable
        }

        stop()

        let audioSession = AVAudioSession.sharedInstance()
        try audioSession.setCategory(.record, mode: .measurement, options: .duckOthers)
        try audioSession.setActive(true, options: .notifyOthersOnDeactivation)

        let request = SFSpeechAudioBufferRecognitionRequest()
        request.shouldReportPartialResults = true
        recognitionRequest = request

        let inputNode = audioEngine.inputNode
        let format = inputNode.outputFormat(forBus: 0)
        inputNode.removeTap(onBus: 0)
        inputNode.installTap(onBus: 0, bufferSize: 1024, format: format) { buffer, _ in
            request.append(buffer)
        }

        recognitionTask = speechRecognizer.recognitionTask(with: request) { result, error in
            if let result {
                Task { @MainActor in
                    onTranscript(result.bestTranscription.formattedString)
                }
            }
            if error != nil || result?.isFinal == true {
                Task { @MainActor in
                    self.stop()
                }
            }
        }

        audioEngine.prepare()
        try audioEngine.start()
        isRecording = true
    }

    func stop() {
        if audioEngine.isRunning {
            audioEngine.stop()
            audioEngine.inputNode.removeTap(onBus: 0)
        }
        recognitionRequest?.endAudio()
        recognitionRequest = nil
        recognitionTask?.cancel()
        recognitionTask = nil
        isRecording = false
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }

    private func requestPermissions() async throws {
        let speechStatus = await withCheckedContinuation { continuation in
            SFSpeechRecognizer.requestAuthorization { status in
                continuation.resume(returning: status)
            }
        }
        guard speechStatus == .authorized else {
            throw SpeechCaptureError.speechPermissionDenied
        }

        let microphoneAllowed = await requestMicrophonePermission()
        guard microphoneAllowed else {
            throw SpeechCaptureError.microphonePermissionDenied
        }
    }

    private func requestMicrophonePermission() async -> Bool {
        await withCheckedContinuation { continuation in
            if #available(iOS 17.0, *) {
                AVAudioApplication.requestRecordPermission { allowed in
                    continuation.resume(returning: allowed)
                }
            } else {
                AVAudioSession.sharedInstance().requestRecordPermission { allowed in
                    continuation.resume(returning: allowed)
                }
            }
        }
    }
}

enum SpeechCaptureError: LocalizedError {
    case speechPermissionDenied
    case microphonePermissionDenied
    case recognizerUnavailable

    var errorDescription: String? {
        switch self {
        case .speechPermissionDenied:
            "Speech recognition permission is required for voice capture."
        case .microphonePermissionDenied:
            "Microphone permission is required for voice capture."
        case .recognizerUnavailable:
            "Speech recognition is unavailable on this device right now."
        }
    }
}
