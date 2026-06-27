from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol


class SiftRuntimeError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class RuntimeMessage:
    role: str
    content: str


@dataclass(frozen=True)
class RuntimeModelRequest:
    model: str
    messages: tuple[RuntimeMessage, ...]
    response_format: dict[str, Any] | None = None
    temperature: float | None = None
    structured_output_strategy: str | None = None


@dataclass(frozen=True)
class RuntimeModelResponse:
    content: str
    provider: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(frozen=True)
class RuntimeModelDelta:
    content: str


@dataclass(frozen=True)
class RuntimeModelCompleted:
    response: RuntimeModelResponse


RuntimeModelStreamEvent = RuntimeModelDelta | RuntimeModelCompleted


class RuntimeModelProvider(Protocol):
    provider_name: str

    async def complete(self, request: RuntimeModelRequest) -> RuntimeModelResponse:
        ...

    async def stream(self, request: RuntimeModelRequest) -> AsyncIterator[RuntimeModelStreamEvent]:
        ...

    async def list_models(self) -> list[str]:
        ...
