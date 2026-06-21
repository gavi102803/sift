from fastapi import FastAPI
from pydantic import BaseModel

from sift_backend.config import load_settings


class HealthResponse(BaseModel):
    status: str
    env: str


def create_app() -> FastAPI:
    settings = load_settings()
    app = FastAPI(
        title="Sift Backend",
        version="0.1.0",
        description="Backend API for Sift concept learning notes.",
    )

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", env=settings.env)

    return app


app = create_app()

