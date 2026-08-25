"""HTTP surface. Thin: every decision lives in the domain layer."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from ...config import Settings, get_settings
from ...schemas import responses as api
from ..service import BundleNotFoundError, PatientNotFoundError, SnapshotService

VERSION = "0.1.0"

router = APIRouter()


def get_service(settings: Annotated[Settings, Depends(get_settings)]) -> SnapshotService:
    return SnapshotService(
        settings.bundle_path,
        withhold_excluded_values=settings.withhold_excluded_observation_values,
    )


ServiceDep = Annotated[SnapshotService, Depends(get_service)]


@router.get("/api/v1/health", response_model=api.HealthResponse, tags=["meta"])
def health(service: ServiceDep) -> api.HealthResponse:
    """Liveness, plus whether the configured bundle actually loaded."""
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
def get_snapshot(patient_id: str, service: ServiceDep) -> api.SnapshotResponse:
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
def get_excluded(patient_id: str, service: ServiceDep) -> api.ExcludedResponse:
    """Resources retracted at the source. Never current clinical facts."""
    return _guard(lambda: service.excluded(patient_id), patient_id)


@router.get(
    "/api/v1/patients/{patient_id}/data-quality",
    response_model=api.DataQualityResponse,
    tags=["patients"],
)
def get_data_quality(patient_id: str, service: ServiceDep) -> api.DataQualityResponse:
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
            detail=str(exc),
        ) from exc
