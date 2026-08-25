"""API response models.

Deliberately separate from `fhir/models.py`. Those model what the source sent;
these model what we are willing to say. Keeping them apart is what stops a raw
FHIR field leaking to the client without passing through classification.

Field names are snake_case in Python and camelCase on the wire.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class Schema(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, from_attributes=True
    )


# -- primitives ------------------------------------------------------------


class DateValue(Schema):
    """A date with its source precision. `value` is the source string."""

    value: str
    precision: str


class Coding(Schema):
    system: str | None = None
    code: str | None = None
    display: str | None = None
    display_status: str
    system_name: str | None = None
    display_source: str | None = None
    code_system_mismatch: bool = False
    mismatch_reason: str | None = None
    usable_for_coded_logic: bool = True


class ReferenceValue(Schema):
    reference: str
    resolved: bool
    display: str | None = None
    reason: str | None = None


class Provenance(Schema):
    resource_id: str
    admitted_by: str


class Attribution(Schema):
    patient_id: str
    patient_label: str
    candidate_id: str
    note: str


class Warning(Schema):
    code: str
    severity: str
    message: str
    detail: dict[str, str] = {}


class Issue(Schema):
    code: str
    severity: str
    message: str
    resource_id: str | None = None
    resource_type: str | None = None
    path: str | None = None
    detail: dict[str, str] = {}


# -- clinical sections -----------------------------------------------------


class ConditionItem(Schema):
    id: str
    code: Coding
    clinical_status: Coding | None = None
    verification_status: Coding | None = None
    onset: DateValue | None = None
    encounter: ReferenceValue | None = None
    category_declared: bool
    flags: list[str] = []
    provenance: Provenance


class MedicationItem(Schema):
    id: str
    status: str | None = None
    medication: Coding
    dosage_text: str | None = None
    authored_on: DateValue | None = None
    flags: list[str] = []
    provenance: Provenance
    attribution: Attribution | None = None


class AllergyItem(Schema):
    id: str
    code: Coding
    clinical_status: Coding | None = None
    verification_status: Coding | None = None
    criticality: str | None = None
    recorded_date: DateValue | None = None
    flags: list[str] = []
    provenance: Provenance


class ObservationComponent(Schema):
    code: Coding
    value: float | None = None
    unit: str | None = None


class ObservationItem(Schema):
    id: str
    code: Coding
    category_declared: str | None = None
    effective: DateValue | None = None
    value: float | None = None
    unit: str | None = None
    components: list[ObservationComponent] = []
    performer: ReferenceValue | None = None
    encounter: ReferenceValue | None = None
    reference_range_available: bool
    interpretation_available: bool
    flags: list[str] = []
    provenance: Provenance


class EncounterItem(Schema):
    id: str
    status: str | None = None
    encounter_class: Coding | None = None
    type: Coding | None = None
    period_start: DateValue | None = None
    period_end: DateValue | None = None
    flags: list[str] = []
    provenance: Provenance


class ExcludedItem(Schema):
    """A retracted resource. Present so the reader can see that a retraction
    happened; never part of any clinical section."""

    id: str
    resource_type: str
    suppression_reason: str
    suppression_field: str | None = None
    summary: str
    value_withheld: bool = False
    value_withheld_reason: str | None = None


class NeedsReviewItem(Schema):
    id: str
    resource_type: str
    reasons: list[str] = []
    summary: str
    detail: str


# -- patient ---------------------------------------------------------------


class UsCoreExtensions(Schema):
    race: Coding | None = None
    race_text: str | None = None
    ethnicity: Coding | None = None
    ethnicity_text: str | None = None
    birthsex: str | None = None


class PatientIdentifier(Schema):
    system: str | None = None
    system_name: str | None = None
    value: str | None = None
    masked: bool = False


class PatientDetail(Schema):
    id: str
    family_name: str | None = None
    given_names: list[str] = []
    gender: str | None = None
    birth_date: DateValue | None = None
    identifiers: list[PatientIdentifier] = []
    address_lines: list[str] = []
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    telecom: list[tuple[str, str]] = []
    profiles_claimed: list[str] = []
    us_core: UsCoreExtensions


# -- identity --------------------------------------------------------------


class Evidence(Schema):
    signal: str
    detail: str
    strength: str
    direction: str


class CrossRecordResource(Schema):
    resource_id: str
    resource_type: str
    status: str | None = None
    patient_id: str
    note: str


class DuplicateCandidate(Schema):
    candidate_id: str
    member_ids: list[str]
    determination: str
    merge_performed: bool
    source_asserted_link: str | None = None
    evidence_for: list[Evidence] = []
    evidence_against: list[Evidence] = []
    cross_record_resources: list[CrossRecordResource] = []
    recommended_action: str


class IdentityAnalysis(Schema):
    primary_patient_id: str | None = None
    primary_selection_rationale: str
    all_patient_ids: list[str] = []
    candidates: list[DuplicateCandidate] = []


class PatientSummary(Schema):
    id: str
    display: str
    identifiers: list[PatientIdentifier] = []
    birth_date: DateValue | None = None
    gender: str | None = None
    profile_claimed: list[str] = []
    resource_counts: dict[str, int] = {}


# -- envelopes -------------------------------------------------------------


class SnapshotMeta(Schema):
    patient_id: str
    bundle_id: str | None = None
    bundle_timestamp: str | None = None
    latest_clinical_activity: str | None = None
    generated_at: str
    days_since_bundle_export: int | None = None
    days_since_latest_activity: int | None = None
    scope_note: str


class SnapshotData(Schema):
    warnings: list[Warning] = []
    patient: PatientDetail
    conditions_current: list[ConditionItem] = []
    conditions_historical: list[ConditionItem] = []
    conditions_category_declared: bool
    medications_active: list[MedicationItem] = []
    medications_historical: list[MedicationItem] = []
    allergies_current: list[AllergyItem] = []
    allergies_historical: list[AllergyItem] = []
    vital_signs: list[ObservationItem] = []
    other_observations: list[ObservationItem] = []
    encounters: list[EncounterItem] = []
    needs_review: list[NeedsReviewItem] = []
    identity: IdentityAnalysis


class SnapshotResponse(Schema):
    meta: SnapshotMeta
    data: SnapshotData
    issues: list[Issue] = []


class PatientsData(Schema):
    patients: list[PatientSummary] = []
    duplicate_candidates: list[DuplicateCandidate] = []


class PatientsResponse(Schema):
    meta: dict[str, str | int | None]
    data: PatientsData
    issues: list[Issue] = []


class ExcludedData(Schema):
    note: str
    excluded: list[ExcludedItem] = []


class ExcludedResponse(Schema):
    meta: dict[str, str | int | None]
    data: ExcludedData


class DataQualityData(Schema):
    summary: dict[str, int]
    issues: list[Issue] = []


class DataQualityResponse(Schema):
    meta: dict[str, str | int | None]
    data: DataQualityData


class HealthResponse(Schema):
    status: str
    version: str
    bundle_loaded: bool
    bundle_id: str | None = None
    patient_count: int = 0
