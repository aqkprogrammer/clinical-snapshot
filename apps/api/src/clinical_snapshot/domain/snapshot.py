"""Assembles the clinical snapshot.

Ties the pipeline together: classify, resolve terminology, preserve date
precision, resolve references, and route every resource to exactly one
destination. Nothing is dropped -- the conservation property is asserted by the
safety test suite.

Two routing decisions live here rather than in `safety.py`, because they are
about *completeness* rather than record status:

  * An Observation whose code has no resolvable display **and** no category is
    routed to needs-review. We can neither name the analyte nor say what kind
    of measurement it is, so rendering a bare number invites the reader to
    supply a meaning we do not have.
  * Clinical data belonging to an unreconciled duplicate record is attributed,
    not merged and not hidden. See `identity.py`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TypeVar

from ..fhir.loader import LoadedBundle
from ..fhir.models import (
    AllergyIntolerance,
    CodeableConcept,
    Condition,
    DomainResource,
    Encounter,
    Extension,
    MedicationRequest,
    Observation,
    Patient,
    Reference,
)
from ..fhir.resolver import ReferenceResolver, ResolvedReference
from .identity import DuplicateCandidate, IdentityAnalysis, IdentityAnalyzer
from .issues import IssueCode, IssueLog, Severity
from .partial_date import PartialDate
from .safety import Classification, Disposition, Flag, classify
from .terminology import DisplayStatus, ResolvedCoding, TerminologyService

US_CORE = "http://hl7.org/fhir/us/core/StructureDefinition"
RACE_EXT = f"{US_CORE}/us-core-race"
ETHNICITY_EXT = f"{US_CORE}/us-core-ethnicity"
BIRTHSEX_EXT = f"{US_CORE}/us-core-birthsex"

VITAL_SIGNS_CATEGORY = "vital-signs"

T = TypeVar("T")


def _require(value: PartialDate | None) -> PartialDate:
    """Narrow an Optional the caller has already filtered on."""
    assert value is not None
    return value


# --------------------------------------------------------------------------
# View models -- what the API renders
# --------------------------------------------------------------------------


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
    suppression_reason: str
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


@dataclass(frozen=True, slots=True)
class Warning_:
    code: str
    severity: str
    message: str
    detail: dict[str, str] = field(default_factory=dict)


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


# --------------------------------------------------------------------------
# Assembler
# --------------------------------------------------------------------------


class SnapshotAssembler:
    def __init__(
        self,
        loaded: LoadedBundle,
        *,
        withhold_excluded_values: bool = True,
    ) -> None:
        self._loaded = loaded
        self._issues: IssueLog = loaded.issues
        self._terminology = TerminologyService(self._issues)
        self._resolver = ReferenceResolver(loaded.index, self._issues)
        self._withhold = withhold_excluded_values

    # -- public ------------------------------------------------------------

    @property
    def loaded(self) -> LoadedBundle:
        return self._loaded

    @property
    def issues(self) -> IssueLog:
        return self._issues

    def patients(self) -> list[Patient]:
        return [p for p in self._loaded.index.of_type("Patient") if isinstance(p, Patient)]

    def analyse_identity(self) -> IdentityAnalysis:
        return IdentityAnalyzer(self._issues).analyse(self.patients(), self._reference_counts())

    def build(self, patient_id: str, *, as_of: datetime | None = None) -> Snapshot | None:
        patient = next((p for p in self.patients() if p.id == patient_id), None)
        if patient is None:
            return None

        as_of = as_of or datetime.now(UTC)
        identity = self.analyse_identity()
        candidate = identity.candidate_for(patient_id)

        owned = self.resources_for(patient_id)
        classified = [(r, classify(r)) for r in owned]

        conditions_current: list[ConditionView] = []
        conditions_historical: list[ConditionView] = []
        medications_active: list[MedicationView] = []
        medications_historical: list[MedicationView] = []
        allergies_current: list[AllergyView] = []
        allergies_historical: list[AllergyView] = []
        vital_signs: list[ObservationView] = []
        other_observations: list[ObservationView] = []
        encounters: list[EncounterView] = []
        needs_review: list[NeedsReviewView] = []
        excluded: list[ExcludedView] = []

        for resource, classification in classified:
            if classification.disposition is Disposition.EXCLUDED:
                excluded.append(self._build_excluded(resource, classification))
                self._issues.add(
                    IssueCode.RESOURCE_ENTERED_IN_ERROR,
                    Severity.HIGH,
                    f"{resource.key} was retracted at the source via "
                    f"{classification.suppression_field} and is excluded from all "
                    f"clinical sections.",
                    resource_id=resource.id,
                    resource_type=resource.resourceType,
                    path=classification.suppression_field,
                )
                continue

            if classification.disposition is Disposition.NEEDS_REVIEW:
                needs_review.append(
                    self._build_needs_review(resource, (classification.reason or "",))
                )
                continue

            current = classification.disposition is Disposition.CURRENT

            if isinstance(resource, Condition):
                condition = self._build_condition(resource, classification)
                (conditions_current if current else conditions_historical).append(condition)
            elif isinstance(resource, MedicationRequest):
                medication = self._build_medication(resource, classification)
                (medications_active if current else medications_historical).append(medication)
            elif isinstance(resource, AllergyIntolerance):
                allergy = self._build_allergy(resource, classification)
                (allergies_current if current else allergies_historical).append(allergy)
            elif isinstance(resource, Encounter):
                encounters.append(self._build_encounter(resource, classification))
            elif isinstance(resource, Observation):
                observation = self._build_observation(resource, classification)
                blockers = self._observation_blockers(observation)
                # Unnameable AND unclassifiable: a bare number with no analyte
                # and no category invites the reader to supply a meaning we do
                # not have. One blocker alone still renders, with the caveat.
                if len(blockers) >= 2:
                    needs_review.append(
                        self._build_needs_review(resource, blockers, observation)
                    )
                elif observation.category_declared == VITAL_SIGNS_CATEGORY:
                    vital_signs.append(observation)
                else:
                    other_observations.append(observation)

        cross_record = self._build_cross_record_medications(patient_id, candidate, identity)
        medications_active.extend(cross_record)

        self._check_bundle_reference_scheme()
        self._check_us_core(patient)

        latest = self._latest_activity(classified)
        warnings = self._build_warnings(candidate, identity, cross_record, latest, as_of)

        return Snapshot(
            meta=self._build_meta(patient_id, latest, as_of),
            patient=self.build_patient_view(patient),
            warnings=tuple(warnings),
            conditions_current=tuple(self._by_recency(conditions_current, lambda c: c.onset)),
            conditions_historical=tuple(self._by_recency(conditions_historical, lambda c: c.onset)),
            conditions_category_declared=any(
                r.category for r, _ in classified if isinstance(r, Condition)
            ),
            medications_active=tuple(
                self._by_recency(medications_active, lambda m: m.authored_on)
            ),
            medications_historical=tuple(
                self._by_recency(medications_historical, lambda m: m.authored_on)
            ),
            allergies_current=tuple(
                self._by_recency(allergies_current, lambda a: a.recorded_date)
            ),
            allergies_historical=tuple(
                self._by_recency(allergies_historical, lambda a: a.recorded_date)
            ),
            vital_signs=tuple(self._by_recency(vital_signs, lambda o: o.effective)),
            other_observations=tuple(self._by_recency(other_observations, lambda o: o.effective)),
            encounters=tuple(self._by_recency(encounters, lambda e: e.period_start)),
            needs_review=tuple(needs_review),
            excluded=tuple(excluded),
            identity=identity,
        )

    # -- resource scoping --------------------------------------------------

    def _subject_ref(self, resource: DomainResource) -> Reference | None:
        for attribute in ("subject", "patient"):
            ref = getattr(resource, attribute, None)
            if isinstance(ref, Reference):
                return ref
        return None

    def _reference_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for resource in self._loaded.index.all():
            if isinstance(resource, Patient):
                continue
            ref = self._subject_ref(resource)
            if ref and ref.reference:
                counts[ref.reference] = counts.get(ref.reference, 0) + 1
        return counts

    def resources_for(self, patient_id: str) -> list[DomainResource]:
        """Resources whose subject resolves to this patient, and only this one.

        The scope boundary is enforced here and asserted by the safety suite:
        no resource belonging to another Patient record enters a snapshot
        except through the explicit attribution path.
        """
        owned: list[DomainResource] = []
        for resource in self._loaded.index.all():
            if isinstance(resource, Patient):
                continue
            ref = self._subject_ref(resource)
            resolved = self._resolver.resolve(
                ref,
                source_id=resource.id,
                source_type=resource.resourceType,
                path=f"{resource.resourceType}.subject",
            )
            if resolved and resolved.target is not None and resolved.target.id == patient_id:
                owned.append(resource)
        return owned

    # -- builders ----------------------------------------------------------

    def _coding(
        self, concept: CodeableConcept | None, resource: DomainResource, path: str
    ) -> ResolvedCoding:
        primary = concept.primary if concept else None
        return self._terminology.resolve(
            primary.system if primary else None,
            primary.code if primary else None,
            primary.display if primary else (concept.text if concept else None),
            source_id=resource.id,
            source_type=resource.resourceType,
            path=path,
        )

    def _date(self, raw: str | None, resource: DomainResource, path: str) -> PartialDate | None:
        parsed = PartialDate.parse(raw)
        if parsed is None:
            return None
        if parsed.is_reduced_precision:
            self._issues.add(
                IssueCode.DATE_PRECISION_REDUCED,
                Severity.LOW,
                f"{path} is '{parsed.value}' ({parsed.precision.value} precision only). "
                f"Presented as recorded; not expanded to a specific date.",
                resource_id=resource.id,
                resource_type=resource.resourceType,
                path=path,
                detail={"value": parsed.value, "precision": parsed.precision.value},
            )
        return parsed

    def _ref_view(self, resolved: ResolvedReference | None) -> ReferenceView | None:
        if resolved is None:
            return None
        display: str | None = None
        if resolved.target is not None:
            display = self._label_for(resolved.target)
        return ReferenceView(
            reference=resolved.reference,
            resolved=resolved.resolved,
            display=display,
            reason=resolved.reason,
        )

    def _label_for(self, resource: DomainResource) -> str | None:
        if isinstance(resource, Encounter) and resource.type:
            coding = resource.type[0].primary
            if coding and coding.display:
                return coding.display
        return None

    def _build_condition(self, condition: Condition, c: Classification) -> ConditionView:
        if not condition.category:
            self._issues.add(
                IssueCode.CONDITION_CATEGORY_ABSENT,
                Severity.MEDIUM,
                f"{condition.key} has no Condition.category, so it cannot be identified "
                f"as a problem-list item or an encounter diagnosis.",
                resource_id=condition.id,
                resource_type="Condition",
                path="Condition.category",
            )
        return ConditionView(
            id=condition.id or "",
            code=self._coding(condition.code, condition, "Condition.code"),
            clinical_status=self._coding(
                condition.clinicalStatus, condition, "Condition.clinicalStatus"
            ),
            verification_status=self._coding(
                condition.verificationStatus, condition, "Condition.verificationStatus"
            ),
            onset=self._date(condition.onsetDateTime, condition, "Condition.onsetDateTime"),
            encounter=self._ref_view(
                self._resolver.resolve(
                    condition.encounter,
                    source_id=condition.id,
                    source_type="Condition",
                    path="Condition.encounter",
                )
            ),
            category_declared=bool(condition.category),
            flags=c.flags,
            provenance=Provenance(condition.id or "", c.rule),
        )

    def _build_medication(
        self,
        medication: MedicationRequest,
        c: Classification,
        attribution: Attribution | None = None,
    ) -> MedicationView:
        return MedicationView(
            id=medication.id or "",
            status=medication.status,
            medication=self._coding(
                medication.medicationCodeableConcept,
                medication,
                "MedicationRequest.medicationCodeableConcept",
            ),
            dosage_text=(
                medication.dosageInstruction[0].text if medication.dosageInstruction else None
            ),
            authored_on=self._date(
                medication.authoredOn, medication, "MedicationRequest.authoredOn"
            ),
            flags=c.flags,
            provenance=Provenance(medication.id or "", c.rule),
            attribution=attribution,
        )

    def _build_allergy(self, allergy: AllergyIntolerance, c: Classification) -> AllergyView:
        return AllergyView(
            id=allergy.id or "",
            code=self._coding(allergy.code, allergy, "AllergyIntolerance.code"),
            clinical_status=self._coding(
                allergy.clinicalStatus, allergy, "AllergyIntolerance.clinicalStatus"
            ),
            verification_status=self._coding(
                allergy.verificationStatus, allergy, "AllergyIntolerance.verificationStatus"
            ),
            criticality=allergy.criticality,
            recorded_date=self._date(
                allergy.recordedDate, allergy, "AllergyIntolerance.recordedDate"
            ),
            flags=c.flags,
            provenance=Provenance(allergy.id or "", c.rule),
        )

    def _build_observation(self, observation: Observation, c: Classification) -> ObservationView:
        category = None
        if observation.category:
            category = observation.category[0].primary_code
        else:
            self._issues.add(
                IssueCode.OBSERVATION_CATEGORY_ABSENT,
                Severity.MEDIUM,
                f"{observation.key} has no Observation.category, so it cannot be "
                f"classified as a vital sign, a laboratory result, or a survey.",
                resource_id=observation.id,
                resource_type="Observation",
                path="Observation.category",
            )
        if not observation.referenceRange and not observation.interpretation:
            self._issues.add(
                IssueCode.REFERENCE_RANGE_ABSENT,
                Severity.LOW,
                f"{observation.key} has neither referenceRange nor interpretation. No "
                f"high/low or abnormal flag can be derived, and none is shown.",
                resource_id=observation.id,
                resource_type="Observation",
                path="Observation.referenceRange",
            )
        return ObservationView(
            id=observation.id or "",
            code=self._coding(observation.code, observation, "Observation.code"),
            category_declared=category,
            effective=self._date(
                observation.effectiveDateTime, observation, "Observation.effectiveDateTime"
            ),
            value=observation.valueQuantity.value if observation.valueQuantity else None,
            unit=observation.valueQuantity.unit if observation.valueQuantity else None,
            components=tuple(
                ObservationComponentView(
                    code=self._coding(
                        component.code, observation, "Observation.component.code"
                    ),
                    value=component.valueQuantity.value if component.valueQuantity else None,
                    unit=component.valueQuantity.unit if component.valueQuantity else None,
                )
                for component in observation.component
            ),
            performer=self._ref_view(
                self._resolver.resolve(
                    observation.performer[0] if observation.performer else None,
                    source_id=observation.id,
                    source_type="Observation",
                    path="Observation.performer[0]",
                )
            ),
            encounter=self._ref_view(
                self._resolver.resolve(
                    observation.encounter,
                    source_id=observation.id,
                    source_type="Observation",
                    path="Observation.encounter",
                )
            ),
            reference_range_available=bool(observation.referenceRange),
            interpretation_available=bool(observation.interpretation),
            flags=c.flags,
            provenance=Provenance(observation.id or "", c.rule),
        )

    def _build_encounter(self, encounter: Encounter, c: Classification) -> EncounterView:
        return EncounterView(
            id=encounter.id or "",
            status=encounter.status,
            encounter_class=(
                self._terminology.resolve(
                    encounter.class_.system,
                    encounter.class_.code,
                    encounter.class_.display,
                    source_id=encounter.id,
                    source_type="Encounter",
                    path="Encounter.class",
                )
                if encounter.class_
                else None
            ),
            type=(
                self._coding(encounter.type[0], encounter, "Encounter.type")
                if encounter.type
                else None
            ),
            period_start=self._date(
                encounter.period.start if encounter.period else None,
                encounter,
                "Encounter.period.start",
            ),
            period_end=self._date(
                encounter.period.end if encounter.period else None,
                encounter,
                "Encounter.period.end",
            ),
            flags=c.flags,
            provenance=Provenance(encounter.id or "", c.rule),
        )

    def _build_excluded(self, resource: DomainResource, c: Classification) -> ExcludedView:
        withhold = self._withhold and isinstance(resource, Observation) and (
            resource.valueQuantity is not None
        )
        return ExcludedView(
            id=resource.id or "",
            resource_type=resource.resourceType,
            suppression_reason="ENTERED_IN_ERROR",
            suppression_field=c.suppression_field,
            summary=self._summarise(resource),
            value_withheld=withhold,
            value_withheld_reason=(
                "Retracted result; the numeric value is withheld from all views so it "
                "cannot be read as a finding."
                if withhold
                else None
            ),
        )

    def _build_needs_review(
        self,
        resource: DomainResource,
        reasons: tuple[str, ...],
        view: ObservationView | None = None,
    ) -> NeedsReviewView:
        detail = (
            "The analyte cannot be named and the measurement cannot be classified, so "
            "the value is not presented as a clinical result."
            if view is not None
            else "Insufficient information to place this record."
        )
        self._issues.add(
            IssueCode.RESOURCE_NEEDS_REVIEW,
            Severity.MEDIUM,
            f"{resource.key} could not be placed in a clinical section: "
            f"{'; '.join(r for r in reasons if r)}.",
            resource_id=resource.id,
            resource_type=resource.resourceType,
        )
        return NeedsReviewView(
            id=resource.id or "",
            resource_type=resource.resourceType,
            reasons=tuple(r for r in reasons if r),
            summary=self._summarise(resource),
            detail=detail,
        )

    def _observation_blockers(self, view: ObservationView) -> tuple[str, ...]:
        blockers: list[str] = []
        if view.code.display_status is DisplayStatus.UNRESOLVED:
            blockers.append("TERMINOLOGY_DISPLAY_UNRESOLVED")
        if view.category_declared is None:
            blockers.append("OBSERVATION_CATEGORY_ABSENT")
        if view.effective is not None and view.effective.is_reduced_precision:
            blockers.append("DATE_PRECISION_REDUCED")
        return tuple(blockers)

    def _summarise(self, resource: DomainResource) -> str:
        for attribute in ("code", "medicationCodeableConcept"):
            concept = getattr(resource, attribute, None)
            if isinstance(concept, CodeableConcept) and concept.primary:
                coding = concept.primary
                if coding.display:
                    return coding.display
                name = self._terminology.system_name(coding.system) or "code"
                return f"{name} {coding.code} (display unavailable)"
        if isinstance(resource, Encounter):
            when = resource.period.start if resource.period else "date unknown"
            return f"{resource.resourceType} recorded {when}"
        return resource.key

    # -- cross-record disclosure ------------------------------------------

    def _build_cross_record_medications(
        self,
        patient_id: str,
        candidate: DuplicateCandidate | None,
        identity: IdentityAnalysis,
    ) -> list[MedicationView]:
        """Active medications on an unreconciled duplicate record.

        Shown, attributed, and never folded into the subject's own list.
        Hiding an active order is as much a safety failure as misattributing
        one -- if the records are the same person, omitting it breaks
        medication reconciliation.
        """
        if candidate is None or candidate.merge_performed:
            return []

        views: list[MedicationView] = []
        for other_id in candidate.member_ids:
            if other_id == patient_id or not other_id:
                continue
            other = next((p for p in self.patients() if p.id == other_id), None)
            label = self._patient_label(other) if other else other_id
            for resource in self.resources_for(other_id):
                if not isinstance(resource, MedicationRequest):
                    continue
                classification = classify(resource)
                if classification.disposition is not Disposition.CURRENT:
                    continue
                self._issues.add(
                    IssueCode.CROSS_RECORD_CLINICAL_DATA,
                    Severity.HIGH,
                    f"{resource.key} is an active medication on {other_id}, a possible "
                    f"duplicate of {patient_id} that has not been reconciled. It is "
                    f"shown under an explicit attribution and is not merged into the "
                    f"subject's own medication list.",
                    resource_id=resource.id,
                    resource_type=resource.resourceType,
                    detail={"candidateId": candidate.candidate_id, "ownerPatientId": other_id},
                )
                views.append(
                    self._build_medication(
                        resource,
                        classification,
                        attribution=Attribution(
                            patient_id=other_id,
                            patient_label=label,
                            candidate_id=candidate.candidate_id,
                            note=f"Recorded against {label}, a possible duplicate record. "
                            f"Same-person status is NOT confirmed.",
                        ),
                    )
                )
        return views

    def _patient_label(self, patient: Patient) -> str:
        mrn = next(
            (i.value for i in patient.identifier if i.system and i.system.endswith("/mrn")),
            None,
        )
        return mrn or patient.key

    # -- patient view ------------------------------------------------------

    def build_patient_view(self, patient: Patient) -> PatientView:
        name = patient.name[0] if patient.name else None
        address = patient.address[0] if patient.address else None
        return PatientView(
            id=patient.id or "",
            family_name=name.family if name else None,
            given_names=tuple(name.given) if name else (),
            gender=patient.gender,
            birth_date=self._date(patient.birthDate, patient, "Patient.birthDate"),
            identifiers=tuple(
                IdentifierView(
                    system=i.system,
                    system_name=self._terminology.system_name(i.system),
                    value=i.value,
                    masked=bool(i.value and "*" in i.value),
                )
                for i in patient.identifier
            ),
            address_lines=tuple(address.line) if address else (),
            city=address.city if address else None,
            state=address.state if address else None,
            postal_code=address.postalCode if address else None,
            telecom=tuple(
                (t.system or "", t.value or "") for t in patient.telecom if t.value
            ),
            profiles_claimed=tuple(patient.meta.profile) if patient.meta else (),
            us_core=self._build_us_core(patient),
        )

    def _build_us_core(self, patient: Patient) -> UsCoreExtensions:
        def find(url: str) -> Extension | None:
            return next((e for e in patient.extension if e.url == url), None)

        def omb(extension: Extension | None) -> tuple[ResolvedCoding | None, str | None]:
            if extension is None:
                return None, None
            category = extension.sub("ombCategory")
            text = extension.sub("text")
            coding = None
            if category and category.valueCoding:
                coding = self._terminology.resolve(
                    category.valueCoding.system,
                    category.valueCoding.code,
                    category.valueCoding.display,
                    source_id=patient.id,
                    source_type="Patient",
                    path="Patient.extension[us-core-race|ethnicity].ombCategory",
                )
            return coding, (text.valueString if text else None)

        race, race_text = omb(find(RACE_EXT))
        ethnicity, ethnicity_text = omb(find(ETHNICITY_EXT))
        birthsex_ext = find(BIRTHSEX_EXT)
        return UsCoreExtensions(
            race=race,
            race_text=race_text,
            ethnicity=ethnicity,
            ethnicity_text=ethnicity_text,
            birthsex=birthsex_ext.valueCode if birthsex_ext else None,
        )

    # -- checks ------------------------------------------------------------

    def _check_us_core(self, patient: Patient) -> None:
        claimed = patient.meta.profile if patient.meta else []
        if not claimed:
            self._issues.add(
                IssueCode.USCORE_ELEMENT_MISSING,
                Severity.LOW,
                f"{patient.key} declares no meta.profile, so no US Core conformance "
                f"claim can be checked.",
                resource_id=patient.id,
                resource_type="Patient",
                path="Patient.meta.profile",
            )
            return
        must_support = (
            (RACE_EXT, "race"),
            (ETHNICITY_EXT, "ethnicity"),
            (BIRTHSEX_EXT, "birthsex"),
        )
        for url, label in must_support:
            if not any(e.url == url for e in patient.extension):
                self._issues.add(
                    IssueCode.USCORE_ELEMENT_MISSING,
                    Severity.MEDIUM,
                    f"{patient.key} claims the US Core Patient profile but has no "
                    f"us-core-{label} extension, which the profile marks must-support.",
                    resource_id=patient.id,
                    resource_type="Patient",
                    path=f"Patient.extension[us-core-{label}]",
                )

    def _check_bundle_reference_scheme(self) -> None:
        if self._resolver.used_type_id_fallback and not self._issues.with_code(
            IssueCode.BDL_REFERENCE_SCHEME_MISMATCH
        ):
            self._issues.add(
                IssueCode.BDL_REFERENCE_SCHEME_MISMATCH,
                Severity.MEDIUM,
                "Bundle entries are addressed by urn: fullUrl while references between "
                "them are relative. Under strict FHIR resolution a relative reference "
                "has no base to resolve against, so references were matched by "
                "ResourceType/id instead. See fhir/resolver.py for the policy.",
                path="Bundle.entry.fullUrl",
            )

    # -- meta / warnings ---------------------------------------------------

    def _latest_activity(
        self, classified: list[tuple[DomainResource, Classification]]
    ) -> PartialDate | None:
        dates: list[PartialDate] = []
        for resource, classification in classified:
            if classification.disposition is Disposition.EXCLUDED:
                continue
            for attribute in ("effectiveDateTime", "authoredOn", "recordedDate", "onsetDateTime"):
                parsed = PartialDate.parse(getattr(resource, attribute, None))
                if parsed:
                    dates.append(parsed)
            if isinstance(resource, Encounter) and resource.period:
                parsed = PartialDate.parse(resource.period.end or resource.period.start)
                if parsed:
                    dates.append(parsed)
        return max(dates, key=lambda d: d.sort_key()) if dates else None

    def _build_meta(
        self, patient_id: str, latest: PartialDate | None, as_of: datetime
    ) -> SnapshotMeta:
        bundle_timestamp = PartialDate.parse(self._loaded.bundle.timestamp)
        return SnapshotMeta(
            patient_id=patient_id,
            bundle_id=self._loaded.bundle.id,
            bundle_timestamp=self._loaded.bundle.timestamp,
            latest_clinical_activity=latest.value if latest else None,
            generated_at=as_of.isoformat(),
            days_since_bundle_export=(
                (as_of - bundle_timestamp.lower_bound).days if bundle_timestamp else None
            ),
            days_since_latest_activity=((as_of - latest.lower_bound).days if latest else None),
            scope_note=(
                f"Scoped to Patient/{patient_id}. No Patient records were merged. Data "
                f"belonging to other Patient records appears only under an explicit "
                f"attribution."
            ),
        )

    def _build_warnings(
        self,
        candidate: DuplicateCandidate | None,
        identity: IdentityAnalysis,
        cross_record: list[MedicationView],
        latest: PartialDate | None,
        as_of: datetime,
    ) -> list[Warning_]:
        warnings: list[Warning_] = []
        if candidate is not None and not candidate.merge_performed:
            others = [m for m in candidate.member_ids if m != identity.primary_patient_id]
            extra = (
                f" That record carries {len(cross_record)} active medication(s), shown "
                f"below under an explicit attribution."
                if cross_record
                else ""
            )
            warnings.append(
                Warning_(
                    code="DUPLICATE_CANDIDATE_UNRECONCILED",
                    severity="high",
                    message=(
                        f"A possible duplicate Patient record ({', '.join(others)}) shares "
                        f"this patient's name, sex, address and birth year. The source "
                        f"system asserts no link between them and no confirming identifier "
                        f"is available, so they have NOT been merged.{extra}"
                    ),
                    detail={"candidateId": candidate.candidate_id},
                )
            )

        if latest is not None:
            days = (as_of - latest.lower_bound).days
            if days > 180:
                warnings.append(
                    Warning_(
                        code="SNAPSHOT_STALE",
                        severity="medium",
                        message=(
                            f"The most recent clinical activity in this bundle is "
                            f"{latest.describe()}, {days} days before this snapshot was "
                            f"generated. Statuses such as 'active' reflect the source at "
                            f"export time, not today."
                        ),
                        detail={"daysSinceLatestActivity": str(days)},
                    )
                )
        return warnings

    @staticmethod
    def _by_recency(items: list[T], key: Callable[[T], PartialDate | None]) -> list[T]:
        """Most recent first. Items with no date sort last, in bundle order.

        Ordering uses the earliest instant a value could denote, so a
        year-precision date sorts as the start of that year. The precision
        travels into the payload, so the UI can show which orderings are soft.
        """
        dated = [i for i in items if key(i) is not None]
        undated = [i for i in items if key(i) is None]
        dated.sort(key=lambda i: _require(key(i)).sort_key(), reverse=True)
        return dated + undated
