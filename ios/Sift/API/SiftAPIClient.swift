import Foundation

protocol SiftAPIClient {
    func createConcept(_ request: CreateConceptRequest) async throws -> ConceptDTO
    func submitTurn(conceptId: UUID, request: ConceptTurnRequest) async throws -> ConceptTurnResponse
    func mergeProposal(id: UUID) async throws -> ConceptDTO
    func dismissProposal(id: UUID) async throws
}

struct HTTPSiftAPIClient: SiftAPIClient {
    var baseURL: URL
    var urlSession: URLSession = .shared
    var jsonDecoder: JSONDecoder = JSONDecoder()
    var jsonEncoder: JSONEncoder = JSONEncoder()

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

