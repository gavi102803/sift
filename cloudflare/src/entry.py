import json
from asyncio import create_task
from urllib.parse import urlparse
from uuid import UUID, uuid4

import asgi
from workers import WorkerEntrypoint

from sift_worker.ai_sdk_client import configured_provider_client_factory
from sift_worker.app import create_app
from sift_worker.d1 import D1WorkerStore
from sift_worker.errors import PublicError
from sift_worker.services import AuthService, ModelRunService

app = create_app(provider_client_factory=configured_provider_client_factory)


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        run_id = _resume_stream_run_id(request)
        if run_id is not None:
            return await self._resume_stream(request, run_id)
        return await asgi.fetch(app, request, self.env)

    async def _resume_stream(self, request, run_id: str):
        from js import Headers, Response, TextEncoder, TransformStream
        from pyodide.ffi import create_proxy
        from workers import wait_until

        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        store = D1WorkerStore(self.env.DB)
        try:
            principal = await AuthService(store).authenticate(
                _bearer_token(request),
                request.headers.get("X-Sift-Installation", ""),
            )
            provider_key = request.headers.get("X-Sift-Provider-Key", "").strip()
            if not provider_key:
                raise PublicError(
                    "invalid_provider_key",
                    "Check your provider API key.",
                    401,
                )
            service = ModelRunService(store)
            run = await service.get(run_id, principal.owner_id)
            if run.kind not in {"initialConcept", "followUp"}:
                raise PublicError(
                    "request_conflict",
                    "The model run cannot be resumed.",
                    409,
                )
        except PublicError as error:
            return _json_error_response(
                Response,
                Headers,
                request_id,
                error,
            )

        transform = TransformStream.new()
        writer = transform.writable.getWriter()
        encoder = TextEncoder.new()
        stream_open = True

        async def send(payload: dict) -> None:
            nonlocal stream_open
            if not stream_open:
                return
            line = json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
            ) + "\n"
            try:
                await writer.write(encoder.encode(line))
            except Exception:
                stream_open = False

        async def event_sink(event) -> None:
            if event.type in {"stepStarted", "stepRestarted"}:
                await send(
                    {
                        "type": "progress",
                        "progressLabel": event.data.get("label"),
                        "sequence": event.sequence,
                    }
                )
            elif event.type == "deltaReset":
                await send({"type": "reset", "sequence": event.sequence})
            elif event.type == "sourcesReady":
                await send(
                    {
                        "type": "sources",
                        "citations": event.data.get("citations", []),
                        "sequence": event.sequence,
                    }
                )

        async def run_model() -> None:
            nonlocal stream_open
            try:
                arguments = {
                    "web_provider_key": request.headers.get(
                        "X-Sift-Web-Provider-Key", ""
                    ).strip(),
                    "event_sink": event_sink,
                    "live_delta_sink": lambda delta: send(
                        {"type": "delta", "delta": delta}
                    ),
                }
                if run.kind == "initialConcept":
                    completed = await service.execute_initial(
                        run_id,
                        principal,
                        provider_key,
                        client_factory=configured_provider_client_factory,
                        **arguments,
                    )
                else:
                    completed = await service.execute_follow_up(
                        run_id,
                        principal,
                        provider_key,
                        run_maintenance=False,
                        client_factory=configured_provider_client_factory,
                        **arguments,
                    )
                if completed.status == "succeeded":
                    await send(
                        {
                            "type": "completed",
                            "modelRun": completed.model_dump(mode="json", by_alias=True),
                        }
                    )
                elif completed.status == "cancelled":
                    await send({"type": "cancelled", "errorCode": "agent_cancelled"})
                elif completed.status == "failed":
                    await send(
                        {
                            "type": "failed",
                            "errorCode": completed.error_code or "model_run_failed",
                            "errorMessage": completed.error_message,
                        }
                    )
                else:
                    await send({"type": "detached"})
                if run.kind == "followUp" and completed.status == "succeeded":
                    try:
                        await service.run_due_maintenance_for_follow_up(
                            run_id,
                            principal.owner_id,
                            provider_key,
                            client_factory=configured_provider_client_factory,
                        )
                    except Exception:
                        # The parent terminal result is already durable and sent.
                        # Maintenance has its own persisted child-run failure state.
                        pass
            except PublicError as error:
                await send(
                    {
                        "type": (
                            "cancelled" if error.code == "agent_cancelled" else "failed"
                        ),
                        "errorCode": error.code,
                        "errorMessage": error.message,
                    }
                )
            finally:
                if stream_open:
                    try:
                        await writer.close()
                    except Exception:
                        pass
                stream_open = False

        task = create_task(run_model())
        task_proxy = create_proxy(task)
        wait_until(task_proxy)
        task.add_done_callback(lambda _task: task_proxy.destroy())
        headers = Headers.new()
        headers.set("Content-Type", "application/x-ndjson; charset=utf-8")
        headers.set("Cache-Control", "no-store")
        headers.set("X-Accel-Buffering", "no")
        headers.set("X-Request-ID", request_id)
        return Response.new(transform.readable, status=200, headers=headers)


def _resume_stream_run_id(request) -> str | None:
    method = getattr(request.method, "value", str(request.method))
    if method != "POST":
        return None
    segments = urlparse(request.url).path.strip("/").split("/")
    if len(segments) != 4 or segments[:2] != ["v1", "model-runs"]:
        return None
    if segments[3] != "resume-stream":
        return None
    try:
        return str(UUID(segments[2]))
    except ValueError:
        return None


def _bearer_token(request) -> str:
    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    return token if scheme.lower() == "bearer" else ""


def _json_error_response(response_type, headers_type, request_id: str, error: PublicError):
    headers = headers_type.new()
    headers.set("Content-Type", "application/json")
    headers.set("X-Request-ID", request_id)
    return response_type.new(
        json.dumps(
            {
                "error": {
                    "code": error.code,
                    "message": error.message,
                    "requestId": request_id,
                }
            },
            separators=(",", ":"),
        ),
        status=error.status_code,
        headers=headers,
    )
