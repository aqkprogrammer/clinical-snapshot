"""FastAPI application."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api.v1.routes import VERSION, router
from .config import get_settings
from .logging_config import configure_logging, log_event

PROBLEM_JSON = "application/problem+json"


def _problem(
    request: Request, status_code: int, title: str, **extra: object
) -> JSONResponse:
    """An RFC 7807 problem document."""
    return JSONResponse(
        status_code=status_code,
        media_type=PROBLEM_JSON,
        content={
            "type": "about:blank",
            "title": title,
            "status": status_code,
            "instance": str(request.url.path),
            **extra,
        },
    )


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
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
    async def http_problem(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        title = exc.detail if isinstance(exc.detail, str) else "Error"
        return _problem(request, exc.status_code, title)

    @app.exception_handler(RequestValidationError)
    async def validation_problem(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """422s use the same problem+json shape as every other error.

        Field locations are returned so a client can correct the request; the
        rejected values are not echoed back.
        """
        return _problem(
            request,
            422,
            "Request parameters failed validation.",
            errors=[
                {"location": ".".join(str(p) for p in error["loc"]), "message": error["msg"]}
                for error in exc.errors()
            ],
        )

    @app.exception_handler(Exception)
    async def unhandled_problem(request: Request, exc: Exception) -> JSONResponse:
        """Last resort. Logs the type, returns no internals.

        Nothing should reach here -- the service raises typed errors that the
        route layer maps. It exists so that if something does, the client gets
        a well-formed document instead of a stack trace.
        """
        log_event(
            logging.ERROR,
            "unhandled exception",
            path=str(request.url.path),
            error=type(exc).__name__,
        )
        return _problem(request, 500, "Internal server error.")

    return app


app = create_app()
