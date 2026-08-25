"""FastAPI application."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api.v1.routes import VERSION, router
from .config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Clinical Snapshot API",
        version=VERSION,
        description=(
            "Renders a messy FHIR R4 bundle as a clinical snapshot. Retracted "
            "resources are excluded, missing terminology displays are reported rather "
            "than guessed, partial dates keep their precision, and Patient records are "
            "never merged without a source-asserted link."
        ),
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET"],
        allow_headers=["*"],
    )
    app.include_router(router)

    @app.exception_handler(StarletteHTTPException)
    async def problem_json(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        """RFC 7807 problem+json."""
        return JSONResponse(
            status_code=exc.status_code,
            media_type="application/problem+json",
            content={
                "type": "about:blank",
                "title": exc.detail if isinstance(exc.detail, str) else "Error",
                "status": exc.status_code,
                "instance": str(request.url.path),
            },
        )

    return app


app = create_app()
