"""What is safe to show as a current clinical fact.

The single highest-harm decision in this application. The bundle contains four
retracted resources, and they are retracted through *two different mechanisms*:

  - `Observation.status`      = "entered-in-error"   (observation-004)
  - `Encounter.status`        = "entered-in-error"   (encounter-002)
  - `Condition.verificationStatus`        = "entered-in-error"  (condition-002)
  - `AllergyIntolerance.verificationStatus` = "entered-in-error" (allergy-002)

`Condition` and `AllergyIntolerance` have no `status` element at all, so an
implementation that checks `resource.status` catches only half of them. Both of
those resources *also* carry a non-active `clinicalStatus` ("inactive",
"resolved"), which means filtering on `clinicalStatus` alone would hide them
for the wrong reason -- and would still leave the retracted creatinine result
and the phantom encounter on screen.

Hence: `verificationStatus` is evaluated *before* `clinicalStatus`, and the
mechanism that caused a suppression is recorded so it can be shown.

Excluded is not deleted. Retracted resources are routed to a separate,
labelled collection. A snapshot that silently drops a corrected lab result
looks identical to one where the result was never taken, and the fact that a
retraction occurred is itself clinically meaningful.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from ..fhir.models import (
    AllergyIntolerance,
    CodeableConcept,
    Condition,
    DomainResource,
    Encounter,
    MedicationRequest,
    Observation,
)


class Disposition(StrEnum):
    """Where a resource is allowed to appear in the snapshot."""

    CURRENT = "current"
    """Safe to present as a current clinical fact."""

    HISTORICAL = "historical"
    """A real, non-retracted record that is no longer current. Shown, but
    never adjacent to current facts."""

    EXCLUDED = "excluded"
    """Retracted at the source. Never a clinical fact. Visible only in the
    labelled excluded collection."""

    NEEDS_REVIEW = "needs-review"
    """Too incomplete or ambiguous to place. Shown in its own section rather
    than being guessed into one of the others."""


class ExclusionReason(StrEnum):
    """Why a resource may never appear as a current clinical fact.

    Structured rather than free text so exclusions can be counted, filtered,
    and asserted on. Every excluded resource carries one, which is what makes
    the exclusion traceable rather than a silent disappearance.
    """

    ENTERED_IN_ERROR = "entered-in-error"
    """The source retracted the record. It should never have existed."""

    REFUTED = "refuted"
    """The source actively disproved the assertion."""


class Flag(StrEnum):
    """Caveats that travel with a resource that is otherwise displayable."""

    UNCONFIRMED = "unconfirmed"
    CANCELLED = "cancelled"
    ON_HOLD = "on-hold"
    STATUS_ABSENT = "status-absent"


@dataclass(frozen=True, slots=True)
class Classification:
    """Why a resource was placed where it was placed."""

    disposition: Disposition
    rule: str
    reason: str | None = None
    suppression_field: str | None = None
    exclusion_reason: ExclusionReason | None = None
    flags: tuple[Flag, ...] = field(default_factory=tuple)

    @property
    def is_excluded(self) -> bool:
        return self.disposition is Disposition.EXCLUDED


# Statuses that mean "this record should never have existed".
_RETRACTED = frozenset({"entered-in-error", "refuted"})

_UNCONFIRMED_VERIFICATION = frozenset({"unconfirmed", "provisional", "differential"})

_CONDITION_CURRENT = frozenset({"active", "recurrence", "relapse"})
_CONDITION_HISTORICAL = frozenset({"inactive", "remission", "resolved"})

_ALLERGY_CURRENT = frozenset({"active"})
_ALLERGY_HISTORICAL = frozenset({"inactive", "resolved"})

_OBSERVATION_CURRENT = frozenset({"final", "amended", "corrected"})
_OBSERVATION_REVIEW = frozenset({"preliminary", "registered", "cancelled", "unknown"})

_ENCOUNTER_CURRENT = frozenset({"in-progress", "arrived", "triaged", "onleave"})
_ENCOUNTER_HISTORICAL = frozenset({"finished"})

_MEDICATION_CURRENT = frozenset({"active"})
_MEDICATION_HISTORICAL = frozenset({"stopped", "completed", "cancelled", "ended", "expired"})
_MEDICATION_REVIEW = frozenset({"draft", "unknown"})


def _status_code(concept: CodeableConcept | None) -> str | None:
    return concept.primary_code if concept else None


def _retracted(field_name: str, status: str) -> Classification:
    reason = (
        ExclusionReason.ENTERED_IN_ERROR
        if status == "entered-in-error"
        else ExclusionReason.REFUTED
    )
    label = "entered in error" if reason is ExclusionReason.ENTERED_IN_ERROR else "refuted"
    return Classification(
        disposition=Disposition.EXCLUDED,
        rule=f"RULE_{field_name.split('.')[0].upper()}_RETRACTED",
        reason=f"Source marked this record '{status}' via {field_name}. It was {label} "
        f"and is not a current clinical fact.",
        suppression_field=field_name,
        exclusion_reason=reason,
    )


def classify(resource: DomainResource) -> Classification:
    """Place one resource. Pure: no I/O, no issue emission, no side effects."""
    if isinstance(resource, Condition):
        return _classify_condition(resource)
    if isinstance(resource, AllergyIntolerance):
        return _classify_allergy(resource)
    if isinstance(resource, Observation):
        return _classify_observation(resource)
    if isinstance(resource, Encounter):
        return _classify_encounter(resource)
    if isinstance(resource, MedicationRequest):
        return _classify_medication(resource)
    return Classification(
        disposition=Disposition.NEEDS_REVIEW,
        rule="RULE_RESOURCE_TYPE_UNSUPPORTED",
        reason=f"'{resource.resourceType}' is not classified by this application.",
    )


def _classify_condition(condition: Condition) -> Classification:
    verification = _status_code(condition.verificationStatus)
    # Precedence matters: a retracted condition is retracted regardless of what
    # clinicalStatus says about it.
    if verification in _RETRACTED:
        return _retracted("Condition.verificationStatus", verification)

    flags: list[Flag] = []
    if verification in _UNCONFIRMED_VERIFICATION:
        flags.append(Flag.UNCONFIRMED)

    clinical = _status_code(condition.clinicalStatus)
    if clinical is None:
        return Classification(
            Disposition.NEEDS_REVIEW,
            "RULE_CONDITION_CLINICAL_STATUS_ABSENT",
            "Condition.clinicalStatus is absent; the condition cannot be placed as "
            "current or resolved.",
            flags=(*flags, Flag.STATUS_ABSENT),
        )
    if clinical in _CONDITION_CURRENT:
        return Classification(
            Disposition.CURRENT, "RULE_CONDITION_CURRENT", flags=tuple(flags)
        )
    if clinical in _CONDITION_HISTORICAL:
        return Classification(
            Disposition.HISTORICAL, "RULE_CONDITION_HISTORICAL", flags=tuple(flags)
        )
    return Classification(
        Disposition.NEEDS_REVIEW,
        "RULE_CONDITION_CLINICAL_STATUS_UNRECOGNISED",
        f"Unrecognised Condition.clinicalStatus '{clinical}'.",
        flags=tuple(flags),
    )


def _classify_allergy(allergy: AllergyIntolerance) -> Classification:
    verification = _status_code(allergy.verificationStatus)
    if verification in _RETRACTED:
        return _retracted("AllergyIntolerance.verificationStatus", verification)

    flags: list[Flag] = []
    if verification in _UNCONFIRMED_VERIFICATION:
        # An unconfirmed allergy still displays. Suppressing it would risk an
        # exposure; the caveat rides along instead.
        flags.append(Flag.UNCONFIRMED)

    clinical = _status_code(allergy.clinicalStatus)
    if clinical is None:
        return Classification(
            Disposition.NEEDS_REVIEW,
            "RULE_ALLERGY_CLINICAL_STATUS_ABSENT",
            "AllergyIntolerance.clinicalStatus is absent.",
            flags=(*flags, Flag.STATUS_ABSENT),
        )
    if clinical in _ALLERGY_CURRENT:
        return Classification(Disposition.CURRENT, "RULE_ALLERGY_CURRENT", flags=tuple(flags))
    if clinical in _ALLERGY_HISTORICAL:
        return Classification(
            Disposition.HISTORICAL, "RULE_ALLERGY_HISTORICAL", flags=tuple(flags)
        )
    return Classification(
        Disposition.NEEDS_REVIEW,
        "RULE_ALLERGY_CLINICAL_STATUS_UNRECOGNISED",
        f"Unrecognised AllergyIntolerance.clinicalStatus '{clinical}'.",
        flags=tuple(flags),
    )


def _classify_observation(observation: Observation) -> Classification:
    status = observation.status
    if status in _RETRACTED:
        assert status is not None
        return _retracted("Observation.status", status)
    if status is None:
        return Classification(
            Disposition.NEEDS_REVIEW,
            "RULE_OBSERVATION_STATUS_ABSENT",
            "Observation.status is absent.",
            flags=(Flag.STATUS_ABSENT,),
        )
    if status in _OBSERVATION_CURRENT:
        return Classification(Disposition.CURRENT, "RULE_OBSERVATION_CURRENT")
    if status in _OBSERVATION_REVIEW:
        return Classification(
            Disposition.NEEDS_REVIEW,
            "RULE_OBSERVATION_NOT_FINAL",
            f"Observation.status is '{status}'; the result is not final.",
            flags=(Flag.CANCELLED,) if status == "cancelled" else (),
        )
    return Classification(
        Disposition.NEEDS_REVIEW,
        "RULE_OBSERVATION_STATUS_UNRECOGNISED",
        f"Unrecognised Observation.status '{status}'.",
    )


def _classify_encounter(encounter: Encounter) -> Classification:
    status = encounter.status
    if status in _RETRACTED:
        assert status is not None
        return _retracted("Encounter.status", status)
    if status is None:
        return Classification(
            Disposition.NEEDS_REVIEW,
            "RULE_ENCOUNTER_STATUS_ABSENT",
            "Encounter.status is absent.",
            flags=(Flag.STATUS_ABSENT,),
        )
    if status in _ENCOUNTER_CURRENT:
        return Classification(Disposition.CURRENT, "RULE_ENCOUNTER_IN_PROGRESS")
    if status in _ENCOUNTER_HISTORICAL:
        return Classification(Disposition.HISTORICAL, "RULE_ENCOUNTER_FINISHED")
    if status == "cancelled":
        # A cancelled visit is a real record of something that did not happen.
        # It is not retracted, so it is not excluded -- but it is flagged so it
        # is never read as an attended encounter.
        return Classification(
            Disposition.HISTORICAL,
            "RULE_ENCOUNTER_CANCELLED",
            "The encounter was cancelled and did not take place.",
            flags=(Flag.CANCELLED,),
        )
    return Classification(
        Disposition.NEEDS_REVIEW,
        "RULE_ENCOUNTER_STATUS_UNRECOGNISED",
        f"Unrecognised Encounter.status '{status}'.",
    )


def _classify_medication(medication: MedicationRequest) -> Classification:
    status = medication.status
    if status in _RETRACTED:
        assert status is not None
        return _retracted("MedicationRequest.status", status)
    if status is None:
        return Classification(
            Disposition.NEEDS_REVIEW,
            "RULE_MEDICATION_STATUS_ABSENT",
            "MedicationRequest.status is absent.",
            flags=(Flag.STATUS_ABSENT,),
        )
    if status in _MEDICATION_CURRENT:
        return Classification(Disposition.CURRENT, "RULE_MEDICATION_ACTIVE")
    if status == "on-hold":
        return Classification(
            Disposition.CURRENT,
            "RULE_MEDICATION_ON_HOLD",
            "The order is active but currently on hold.",
            flags=(Flag.ON_HOLD,),
        )
    if status in _MEDICATION_HISTORICAL:
        return Classification(
            Disposition.HISTORICAL,
            "RULE_MEDICATION_HISTORICAL",
            f"MedicationRequest.status is '{status}'.",
        )
    if status in _MEDICATION_REVIEW:
        return Classification(
            Disposition.NEEDS_REVIEW,
            "RULE_MEDICATION_NOT_ORDERED",
            f"MedicationRequest.status is '{status}'; the order is not established.",
        )
    return Classification(
        Disposition.NEEDS_REVIEW,
        "RULE_MEDICATION_STATUS_UNRECOGNISED",
        f"Unrecognised MedicationRequest.status '{status}'.",
    )


def allergy_prominence(allergy: AllergyIntolerance) -> tuple[int, int]:
    """Ordering key for allergies: most actionable first.

    A confirmed high-criticality allergy is the single most consequential item
    on a clinical snapshot, so it sorts above an unconfirmed one regardless of
    when each was recorded. Both keys read explicit source fields; nothing is
    inferred about severity that the source did not state.

    Lower sorts first.
    """
    criticality_rank = {"high": 0, "low": 2, "unable-to-assess": 3}
    verification = _status_code(allergy.verificationStatus)
    return (
        criticality_rank.get(allergy.criticality or "", 4),
        0 if verification == "confirmed" else 1,
    )
