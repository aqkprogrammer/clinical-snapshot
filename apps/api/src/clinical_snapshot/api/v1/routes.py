"""HTTP surface. Thin: every decision lives in the domain layer."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi import Path as PathParam

from ...config import Settings, get_settings
from ...schemas import responses as api
from ..service import (
    BundleNotFoundError,
    BundleUnreadableError,
    PatientNotFoundError,
    SnapshotService,
)

VERSION = "0.1.0"

# FHIR `id` datatype: 1-64 characters of A-Z, a-z, 0-9, hyphen and dot.
# Constraining the path parameter here means anything outside that charset is
# rejected by the framework as 422 before a handler runs -- which keeps
# unvalidated input out of the log line and out of the 404 body.
FHIR_ID_PATTERN = r"^[A-Za-z0-9\-.]{1,64}$"

PatientId = Annotated[
    str,
    PathParam(
        pattern=FHIR_ID_PATTERN,
        description="A FHIR resource id: 1-64 characters of A-Za-z0-9, '-' and '.'.",
        examples=["patient-001"],
    ),
]

router = APIRouter()


def get_service(settings: Annotated[Settings, Depends(get_settings)]) -> SnapshotService:
    return SnapshotService(
        settings.bundle_path,
        withhold_excluded_values=settings.withhold_excluded_observation_values,
    )


ServiceDep = Annotated[SnapshotService, Depends(get_service)]


@router.get("/api/v1/health", response_model=api.HealthResponse, tags=["meta"])
def health(service: ServiceDep) -> api.HealthResponse:
    """Liveness, plus whether the configured bundle actually loaded.

    Always 200 while the process is serving: this is a liveness probe, and a
    probe that fails when the bundle is corrupt would prevent the stack coming
    up at all rather than letting it come up and say what is wrong. A readiness
    probe should require `bundleLoaded` to be true.
    """
    return service.health(VERSION)


@router.get(
    "/health",
    response_model=api.HealthResponse,
    tags=["meta"],
    include_in_schema=False,
)
def health_alias(service: ServiceDep) -> api.HealthResponse:
    """Unversioned alias, kept for container health checks."""
    return service.health(VERSION)


@router.get("/api/v1/patients", response_model=api.PatientsResponse, tags=["patients"])
def list_patients(service: ServiceDep) -> api.PatientsResponse:
    """Every Patient record in the bundle, plus any unreconciled duplicate
    candidates with the evidence on both sides."""
    return _guard(lambda: service.patients())


@router.get(
    "/api/v1/patients/{patient_id}/snapshot",
    response_model=api.SnapshotResponse,
    tags=["patients"],
)
def get_snapshot(patient_id: PatientId, service: ServiceDep) -> api.SnapshotResponse:
    """The clinical snapshot for one patient.

    Scoped to a single Patient record. Retracted resources are not included --
    see the /excluded endpoint.
    """
    return _guard(lambda: service.snapshot(patient_id), patient_id)


@router.get(
    "/api/v1/patients/{patient_id}/excluded",
    response_model=api.ExcludedResponse,
    tags=["patients"],
)
def get_excluded(patient_id: PatientId, service: ServiceDep) -> api.ExcludedResponse:
    """Resources retracted at the source. Never current clinical facts."""
    return _guard(lambda: service.excluded(patient_id), patient_id)


@router.get(
    "/api/v1/patients/{patient_id}/data-quality",
    response_model=api.DataQualityResponse,
    tags=["patients"],
)
def get_data_quality(patient_id: PatientId, service: ServiceDep) -> api.DataQualityResponse:
    """Every data-quality issue detected while building this snapshot."""
    return _guard(lambda: service.data_quality(patient_id), patient_id)


def _guard(action, patient_id: str | None = None):  # type: ignore[no-untyped-def]
    try:
        return action()
    except PatientNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No Patient resource with id '{patient_id}' in this bundle.",
        ) from exc
    except BundleNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The configured FHIR bundle is not available.",
        ) from exc
    except BundleUnreadableError as exc:
        # The detail is deliberately generic: it would otherwise disclose a
        # filesystem path. The specifics are logged by the service.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The configured FHIR bundle could not be parsed.",
        ) from exc
