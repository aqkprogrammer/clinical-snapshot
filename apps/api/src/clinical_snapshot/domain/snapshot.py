"""The normalized read model.

`Snapshot` is what a clinician reads. `NormalizationResult` wraps it with
everything the application had to decide along the way -- what was withheld,
what conflicted, what could not be resolved -- so a consumer can always answer
"what was thrown away, and why?" without reading a log.

The frontend consumes these shapes and never sees FHIR.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .identity import IdentityAnalysis
from .issues import DataQualityIssue
from .views import (
    AllergyView,
    ConditionView,
    EncounterView,
    ExcludedView,
    MedicationView,
    NeedsReviewView,
    ObservationView,
    PatientView,
    Warning_,
)


@dataclass(frozen=True, slots=True)
class SnapshotMeta:
    patient_id: str
    bundle_id: str | None
    bundle_timestamp: str | None
    latest_clinical_activity: str | None
    generated_at: str
    days_since_bundle_export: int | None
    days_since_latest_activity: int | None
    scope_note: str


@dataclass(frozen=True, slots=True)
class UnresolvedReferenceRecord:
    """A reference that could not be used, and the element it came from.

    Collected separately from the issue log so a consumer can enumerate broken
    links without filtering issue codes.
    """

    source_resource_id: str | None
    source_resource_type: str
    path: str
    reference: str
    status: str
    reason: str | None


@dataclass(frozen=True, slots=True)
class Conflict:
    """A contradiction the source left unresolved, surfaced rather than settled."""

    kind: str
    summary: str
    detail: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Snapshot:
    meta: SnapshotMeta
    patient: PatientView
    warnings: tuple[Warning_, ...]
    conditions_current: tuple[ConditionView, ...]
    conditions_historical: tuple[ConditionView, ...]
    conditions_category_declared: bool
    medications_active: tuple[MedicationView, ...]
    medications_historical: tuple[MedicationView, ...]
    allergies_current: tuple[AllergyView, ...]
    allergies_historical: tuple[AllergyView, ...]
    vital_signs: tuple[ObservationView, ...]
    other_observations: tuple[ObservationView, ...]
    encounters: tuple[EncounterView, ...]
    needs_review: tuple[NeedsReviewView, ...]
    excluded: tuple[ExcludedView, ...]
    identity: IdentityAnalysis


@dataclass(frozen=True, slots=True)
class NormalizationResult:
    """Everything one normalization pass produced.

    The snapshot is what a clinician reads; the other four fields are what the
    application had to decide along the way. Keeping them beside the snapshot
    rather than in a log is the point -- a consumer can always answer "what was
    thrown away, and why?".

    Normalization is deterministic: the same bundle and the same `as_of`
    produce an identical result.
    """

    snapshot: Snapshot
    excluded: tuple[ExcludedView, ...] = field(default_factory=tuple)
    conflicts: tuple[Conflict, ...] = field(default_factory=tuple)
    unresolved_references: tuple[UnresolvedReferenceRecord, ...] = field(default_factory=tuple)
    warnings: tuple[Warning_, ...] = field(default_factory=tuple)
    issues: tuple[DataQualityIssue, ...] = field(default_factory=tuple)

    @property
    def is_clean(self) -> bool:
        return not (self.conflicts or self.unresolved_references or self.warnings)
