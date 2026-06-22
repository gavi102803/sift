import Foundation

protocol SiftAPIClient {
    func listConcepts() async throws -> [ConceptDTO]
    func getConcept(id: UUID) async throws -> ConceptDTO
    func listTurns(conceptId: UUID) async throws -> [ConceptHistoryTurnDTO]
    func createConcept(_ request: CreateConceptRequest) async throws -> ConceptDTO
    func submitTurn(conceptId: UUID, request: ConceptTurnRequest) async throws -> ConceptTurnResponse
    func mergeProposal(id: UUID) async throws -> ConceptDTO
    func dismissProposal(id: UUID) async throws
}

enum SiftAPIClientFactory {
    static func makeDefault() -> any SiftAPIClient {
        if let baseURL = configuredBackendBaseURL() {
            return HTTPSiftAPIClient(baseURL: baseURL)
        }
        return MockSiftAPIClient()
    }

    private static func configuredBackendBaseURL() -> URL? {
        if let value = ProcessInfo.processInfo.environment["SIFT_BACKEND_BASE_URL"],
           let url = URL(string: value),
           !value.isEmpty {
            return url
        }

        if let value = Bundle.main.object(forInfoDictionaryKey: "SIFTBackendBaseURL") as? String,
           let url = URL(string: value),
           !value.isEmpty {
            return url
        }

        return nil
    }
}

struct HTTPSiftAPIClient: SiftAPIClient {
    var baseURL: URL
    var urlSession: URLSession = .shared
    var jsonDecoder: JSONDecoder = JSONDecoder()
    var jsonEncoder: JSONEncoder = JSONEncoder()

    func listConcepts() async throws -> [ConceptDTO] {
        try await get(path: "/v1/concepts")
    }

    func getConcept(id: UUID) async throws -> ConceptDTO {
        try await get(path: "/v1/concepts/\(id.uuidString)")
    }

    func listTurns(conceptId: UUID) async throws -> [ConceptHistoryTurnDTO] {
        try await get(path: "/v1/concepts/\(conceptId.uuidString)/turns")
    }

    func createConcept(_ request: CreateConceptRequest) async throws -> ConceptDTO {
        try await post(path: "/v1/concepts", body: request)
    }

    func submitTurn(conceptId: UUID, request: ConceptTurnRequest) async throws -> ConceptTurnResponse {
        try await post(path: "/v1/concepts/\(conceptId.uuidString)/turns", body: request)
    }

    func mergeProposal(id: UUID) async throws -> ConceptDTO {
        try await post(path: "/v1/update-proposals/\(id.uuidString)/merge", body: EmptyRequest())
    }

    func dismissProposal(id: UUID) async throws {
        let _: EmptyResponse = try await post(
            path: "/v1/update-proposals/\(id.uuidString)/dismiss",
            body: EmptyRequest()
        )
    }

    private func get<Response: Decodable>(path: String) async throws -> Response {
        let urlRequest = URLRequest(url: baseURL.appending(path: path))
        let (data, response) = try await urlSession.data(for: urlRequest)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw SiftAPIError.invalidResponse
        }
        guard (200..<300).contains(httpResponse.statusCode) else {
            throw SiftAPIError.httpStatus(httpResponse.statusCode)
        }
        return try jsonDecoder.decode(Response.self, from: data)
    }

    private func post<Request: Encodable, Response: Decodable>(
        path: String,
        body: Request
    ) async throws -> Response {
        var urlRequest = URLRequest(url: baseURL.appending(path: path))
        urlRequest.httpMethod = "POST"
        urlRequest.setValue("application/json", forHTTPHeaderField: "Content-Type")
        urlRequest.httpBody = try jsonEncoder.encode(body)

        let (data, response) = try await urlSession.data(for: urlRequest)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw SiftAPIError.invalidResponse
        }
        guard (200..<300).contains(httpResponse.statusCode) else {
            throw SiftAPIError.httpStatus(httpResponse.statusCode)
        }
        if Response.self == EmptyResponse.self {
            return EmptyResponse() as! Response
        }
        return try jsonDecoder.decode(Response.self, from: data)
    }
}

enum SiftAPIError: LocalizedError {
    case invalidResponse
    case httpStatus(Int)

    var errorDescription: String? {
        switch self {
        case .invalidResponse:
            "The server returned an invalid response."
        case .httpStatus(let status):
            "The server returned status \(status)."
        }
    }
}

private struct EmptyRequest: Codable {}
private struct EmptyResponse: Codable {}
