"""View models -- the shapes the API is willing to render.

Deliberately separate from `fhir/models.py`, which models what the source
*sent*. These model what we are willing to *say*: every field here has passed
through classification, terminology resolution and precision preservation, and
each carries enough provenance to answer "where did this come from?".

Pure data. No behaviour, no I/O, no construction logic -- that is
`assembler.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .partial_date import PartialDate
from .safety import ExclusionReason, Flag
from .terminology import ResolvedCoding

US_CORE = "http://hl7.org/fhir/us/core/StructureDefinition"
RACE_EXT = f"{US_CORE}/us-core-race"
ETHNICITY_EXT = f"{US_CORE}/us-core-ethnicity"
BIRTHSEX_EXT = f"{US_CORE}/us-core-birthsex"

VITAL_SIGNS_CATEGORY = "vital-signs"

# Identifier systems that never leave the backend. A clinical snapshot needs a
# medical record number to be useful -- it is how a duplicate record is named
# to a reviewer -- but it has no use for a national identifier, so the SSN is
# withheld rather than merely masked. The count of withheld identifiers is
# reported so the omission is visible instead of looking like absent data.
SUPPRESSED_IDENTIFIER_SYSTEMS = frozenset({"http://hl7.org/fhir/sid/us-ssn"})

@dataclass(frozen=True, slots=True)
class ReferenceView:
    reference: str
    resolved: bool
    display: str | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class Provenance:
    resource_id: str
    admitted_by: str


@dataclass(frozen=True, slots=True)
class Attribution:
    """Marks data that belongs to a different Patient record than the subject."""

    patient_id: str
    patient_label: str
    candidate_id: str
    note: str


@dataclass(frozen=True, slots=True)
class ConditionView:
    id: str
    code: ResolvedCoding
    clinical_status: ResolvedCoding | None
    verification_status: ResolvedCoding | None
    onset: PartialDate | None
    encounter: ReferenceView | None
    category_declared: bool
    flags: tuple[Flag, ...]
    provenance: Provenance


@dataclass(frozen=True, slots=True)
class MedicationView:
    id: str
    status: str | None
    medication: ResolvedCoding
    dosage_text: str | None
    authored_on: PartialDate | None
    flags: tuple[Flag, ...]
    provenance: Provenance
    attribution: Attribution | None = None


@dataclass(frozen=True, slots=True)
class AllergyView:
    id: str
    code: ResolvedCoding
    clinical_status: ResolvedCoding | None
    verification_status: ResolvedCoding | None
    criticality: str | None
    recorded_date: PartialDate | None
    flags: tuple[Flag, ...]
    provenance: Provenance


@dataclass(frozen=True, slots=True)
class ObservationComponentView:
    code: ResolvedCoding
    value: float | None
    unit: str | None


@dataclass(frozen=True, slots=True)
class ObservationView:
    id: str
    code: ResolvedCoding
    category_declared: str | None
    effective: PartialDate | None
    value: float | None
    unit: str | None
    components: tuple[ObservationComponentView, ...]
    performer: ReferenceView | None
    encounter: ReferenceView | None
    reference_range_available: bool
    interpretation_available: bool
    flags: tuple[Flag, ...]
    provenance: Provenance


@dataclass(frozen=True, slots=True)
class EncounterView:
    id: str
    status: str | None
    encounter_class: ResolvedCoding | None
    type: ResolvedCoding | None
    period_start: PartialDate | None
    period_end: PartialDate | None
    flags: tuple[Flag, ...]
    provenance: Provenance


@dataclass(frozen=True, slots=True)
class ExcludedView:
    id: str
    resource_type: str
    suppression_reason: ExclusionReason
    suppression_field: str | None
    summary: str
    value_withheld: bool = False
    value_withheld_reason: str | None = None


@dataclass(frozen=True, slots=True)
class NeedsReviewView:
    id: str
    resource_type: str
    reasons: tuple[str, ...]
    summary: str
    detail: str


@dataclass(frozen=True, slots=True)
class UsCoreExtensions:
    race: ResolvedCoding | None
    race_text: str | None
    ethnicity: ResolvedCoding | None
    ethnicity_text: str | None
    birthsex: str | None


@dataclass(frozen=True, slots=True)
class IdentifierView:
    system: str | None
    system_name: str | None
    value: str | None
    masked: bool


@dataclass(frozen=True, slots=True)
class PatientView:
    id: str
    family_name: str | None
    given_names: tuple[str, ...]
    gender: str | None
    birth_date: PartialDate | None
    identifiers: tuple[IdentifierView, ...]
    address_lines: tuple[str, ...]
    city: str | None
    state: str | None
    postal_code: str | None
    telecom: tuple[tuple[str, str], ...]
    profiles_claimed: tuple[str, ...]
    us_core: UsCoreExtensions
    withheld_identifier_count: int = 0


@dataclass(frozen=True, slots=True)
class Warning_:
    code: str
    severity: str
    message: str
    detail: dict[str, str] = field(default_factory=dict)
