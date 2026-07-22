from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Protocol


class RuntimeExecutionObserver(Protocol):
    def model_call_started(self) -> None: ...

    def tool_call_started(self, tool_name: str) -> None: ...


class RuntimeExecutionPolicyError(RuntimeError):
    pass


_observer: ContextVar[RuntimeExecutionObserver | None] = ContextVar(
    "sift_runtime_execution_observer",
    default=None,
)


@contextmanager
def observe_runtime(observer: RuntimeExecutionObserver) -> Iterator[None]:
    token = _observer.set(observer)
    try:
        yield
    finally:
        _observer.reset(token)


def record_model_call() -> None:
    observer = _observer.get()
    if observer is not None:
        observer.model_call_started()


def record_tool_call(tool_name: str) -> None:
    observer = _observer.get()
    if observer is not None:
        observer.tool_call_started(tool_name)
