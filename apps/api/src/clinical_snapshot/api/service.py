"""Application service: loads a bundle and maps domain views onto the wire.

The bundle is re-loaded per request. It is 16 KB, and a fresh load guarantees
a fresh issue log -- caching the parsed bundle while accumulating issues into
a shared collector is a class of bug worth designing out rather than testing
for.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from ..domain.issues import DataQualityIssue, IssueLog
from ..domain.snapshot import Snapshot, SnapshotAssembler
from ..fhir.loader import load_bundle
from ..fhir.models import Patient
from ..schemas import responses as api


class BundleNotFoundError(FileNotFoundError):
    pass


class PatientNotFoundError(LookupError):
    pass


class SnapshotService:
    def __init__(self, bundle_path: Path, *, withhold_excluded_values: bool = True) -> None:
        self._path = bundle_path
        self._withhold = withhold_excluded_values

    # -- loading -----------------------------------------------------------

    def _assembler(self) -> SnapshotAssembler:
        if not self._path.exists():
            raise BundleNotFoundError(f"Bundle not found at {self._path}")
        loaded = load_bundle(self._path)
        return SnapshotAssembler(loaded, withhold_excluded_values=self._withhold)

    # -- endpoints ---------------------------------------------------------

    def health(self, version: str) -> api.HealthResponse:
        try:
            assembler = self._assembler()
        except BundleNotFoundError:
            return api.HealthResponse(
                status="degraded", version=version, bundle_loaded=False, patient_count=0
            )
        return api.HealthResponse(
            status="ok",
            version=version,
            bundle_loaded=True,
            bundle_id=assembler.loaded.bundle.id,
            patient_count=len(assembler.patients()),
        )

    def patients(self) -> api.PatientsResponse:
        assembler = self._assembler()
        identity = assembler.analyse_identity()
        issues = assembler.issues

        summaries: list[api.PatientSummary] = []
        for patient in assembler.patients():
            owned = assembler.resources_for(patient.id or "")
            counts: dict[str, int] = {}
            for resource in owned:
                counts[resource.resourceType] = counts.get(resource.resourceType, 0) + 1
            view = assembler.build_patient_view(patient)
            summaries.append(
                api.PatientSummary(
                    id=patient.id or "",
                    display=_display_name(patient),
                    identifiers=[
                        api.PatientIdentifier.model_validate(asdict(i)) for i in view.identifiers
                    ],
                    birth_date=(
                        api.DateValue.model_validate(asdict(view.birth_date))
                        if view.birth_date
                        else None
                    ),
                    gender=patient.gender,
                    profile_claimed=list(view.profiles_claimed),
                    resource_counts=counts,
                )
            )

        return api.PatientsResponse(
            meta=_bundle_meta(assembler),
            data=api.PatientsData(
                patients=summaries,
                duplicate_candidates=[
                    api.DuplicateCandidate.model_validate(asdict(c)) for c in identity.candidates
                ],
            ),
            issues=_issues(issues),
        )

    def snapshot(self, patient_id: str, *, as_of: datetime | None = None) -> api.SnapshotResponse:
        assembler = self._assembler()
        snapshot = assembler.build(patient_id, as_of=as_of)
        if snapshot is None:
            raise PatientNotFoundError(patient_id)
        return _to_snapshot_response(snapshot, assembler.issues)

    def excluded(self, patient_id: str) -> api.ExcludedResponse:
        assembler = self._assembler()
        snapshot = assembler.build(patient_id)
        if snapshot is None:
            raise PatientNotFoundError(patient_id)
        return api.ExcludedResponse(
            meta=_bundle_meta(assembler),
            data=api.ExcludedData(
                note=(
                    "These resources were retracted at the source and are NOT current "
                    "clinical facts. They are listed so the reader can see that a "
                    "retraction occurred; they never appear in any clinical section."
                ),
                excluded=[api.ExcludedItem.model_validate(asdict(e)) for e in snapshot.excluded],
            ),
        )

    def data_quality(self, patient_id: str) -> api.DataQualityResponse:
        assembler = self._assembler()
        snapshot = assembler.build(patient_id)
        if snapshot is None:
            raise PatientNotFoundError(patient_id)
        issues = assembler.issues
        return api.DataQualityResponse(
            meta=_bundle_meta(assembler),
            data=api.DataQualityData(summary=issues.summary(), issues=_issues(issues)),
        )


# -- mapping helpers -------------------------------------------------------


def _display_name(patient: Patient) -> str:
    if not patient.name:
        return patient.id or "Unknown"
    name = patient.name[0]
    return " ".join([*name.given, name.family or ""]).strip() or (patient.id or "Unknown")


def _bundle_meta(assembler: SnapshotAssembler) -> dict[str, Any]:
    bundle = assembler.loaded.bundle
    return {
        "bundleId": bundle.id,
        "bundleType": bundle.type,
        "bundleTimestamp": bundle.timestamp,
        "entryCount": len(bundle.entry),
    }


def _issues(log: IssueLog) -> list[api.Issue]:
    return [_issue(i) for i in log.all()]


def _issue(issue: DataQualityIssue) -> api.Issue:
    return api.Issue(
        code=issue.code.value,
        severity=issue.severity.value,
        message=issue.message,
        resource_id=issue.resource_id,
        resource_type=issue.resource_type,
        path=issue.path,
        detail=issue.detail,
    )


def _to_snapshot_response(snapshot: Snapshot, issues: IssueLog) -> api.SnapshotResponse:
    raw = asdict(snapshot)
    meta = raw.pop("meta")
    # Retracted resources are served by their own endpoint so they can never be
    # rendered alongside clinical sections by accident.
    raw.pop("excluded")
    return api.SnapshotResponse(
        meta=api.SnapshotMeta.model_validate(meta),
        data=api.SnapshotData.model_validate(raw),
        issues=_issues(issues),
    )
