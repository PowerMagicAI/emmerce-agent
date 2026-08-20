"""HTTP interface (FastAPI). Thin adapters over application services."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from emmerce_agent.domain.errors import DomainError, PermissionDenied, RateLimited, ValidationFailed
from emmerce_agent.infrastructure.composition import build_container
from emmerce_agent.infrastructure.config.settings import Settings
from emmerce_agent.interfaces.api.routes_resources import router as resources_router
from emmerce_agent.interfaces.api.routes_sessions import router as sessions_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings.from_env()
    app.state.container = build_container(settings)
    yield


def create_app() -> FastAPI:
    settings = Settings.from_env()
    app = FastAPI(
        title="Emmerce Agent API",
        version="0.2.1",
        description="生产分层架构：LLM tool-calling + Schema + 结果校验",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(sessions_router)
    app.include_router(resources_router)

    @app.exception_handler(PermissionDenied)
    async def _permission_denied(_request: Request, exc: PermissionDenied):
        return JSONResponse(
            status_code=403,
            content={"code": exc.code, "message": exc.message},
        )

    @app.exception_handler(ValidationFailed)
    async def _validation_failed(_request: Request, exc: ValidationFailed):
        return JSONResponse(
            status_code=400,
            content={"code": exc.code, "message": exc.message},
        )

    @app.exception_handler(RateLimited)
    async def _rate_limited(_request: Request, exc: RateLimited):
        return JSONResponse(
            status_code=429,
            content={"code": exc.code, "message": exc.message},
        )

    @app.exception_handler(DomainError)
    async def _domain_error(_request: Request, exc: DomainError):
        return JSONResponse(
            status_code=400,
            content={"code": exc.code, "message": exc.message},
        )

    @app.get("/health")
    def health():
        container = getattr(app.state, "container", None)
        settings = container.settings if container else Settings.from_env()
        return {
            "status": "ok",
            "service": "emmerce-agent",
            "architecture": "hexagonal-v2",
            "llm_provider": settings.llm_provider,
            "llm_model": settings.llm_model,
        }

    return app


app = create_app()
