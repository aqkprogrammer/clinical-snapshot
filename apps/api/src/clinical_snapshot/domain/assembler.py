"""Builds a `Snapshot` from a loaded bundle.

Ties the pipeline together: classify, resolve terminology, preserve date
precision, resolve references, and route every resource to exactly one
destination. Nothing is dropped -- the conservation property is asserted by the
safety test suite.

Two routing decisions live here rather than in `safety.py`, because they are
about *completeness* rather than record status:

  * An Observation that can be neither named nor classified is routed to
    needs-review -- rendering a bare number with no analyte invites the reader
    to supply a meaning we do not have. See `renderability.py`.
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
from ..fhir.resolver import ReferenceResolver, ResolutionResult, ResolutionStatus
from .identity import DuplicateCandidate, IdentityAnalysis, IdentityAnalyzer
from .issues import IssueCode, IssueLog, Severity
from .partial_date import PartialDate
from .renderability import assess_observation
from .safety import (
    Classification,
    Disposition,
    ExclusionReason,
    allergy_prominence,
    classify,
)
from .snapshot import (
    Conflict,
    NormalizationResult,
    Snapshot,
    SnapshotMeta,
    UnresolvedReferenceRecord,
)
from .terminology import ResolvedCoding, TerminologyService
from .views import (
    BIRTHSEX_EXT,
    ETHNICITY_EXT,
    RACE_EXT,
    SUPPRESSED_IDENTIFIER_SYSTEMS,
    VITAL_SIGNS_CATEGORY,
    AllergyView,
    Attribution,
    ConditionView,
    EncounterView,
    ExcludedView,
    IdentifierView,
    MedicationView,
    NeedsReviewView,
    ObservationComponentView,
    ObservationView,
    PatientView,
    Provenance,
    ReferenceView,
    UsCoreExtensions,
    Warning_,
)

_RESOLUTION_ISSUES: dict[ResolutionStatus, tuple[IssueCode, Severity]] = {
    ResolutionStatus.UNRESOLVED: (IssueCode.REFERENCE_UNRESOLVED, Severity.MEDIUM),
    ResolutionStatus.MALFORMED: (IssueCode.REFERENCE_MALFORMED, Severity.HIGH),
    ResolutionStatus.TYPE_MISMATCH: (IssueCode.REFERENCE_TYPE_MISMATCH, Severity.HIGH),
}

T = TypeVar("T")


@dataclass
class _Sections:
    """Mutable accumulator for one patient's snapshot sections.

    Exists so `_route` has a single typed destination to append to, instead of
    eleven parallel locals threaded through the loop.
    """

    conditions_current: list[ConditionView] = field(default_factory=list)
    conditions_historical: list[ConditionView] = field(default_factory=list)
    medications_active: list[MedicationView] = field(default_factory=list)
    medications_historical: list[MedicationView] = field(default_factory=list)
    allergies_current: list[AllergyView] = field(default_factory=list)
    allergies_historical: list[AllergyView] = field(default_factory=list)
    vital_signs: list[ObservationView] = field(default_factory=list)
    other_observations: list[ObservationView] = field(default_factory=list)
    encounters: list[EncounterView] = field(default_factory=list)
    needs_review: list[NeedsReviewView] = field(default_factory=list)
    excluded: list[ExcludedView] = field(default_factory=list)


def _require(value: PartialDate | None) -> PartialDate:
    """Narrow an Optional the caller has already filtered on."""
    assert value is not None
    return value


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
        self._resolver = ReferenceResolver(loaded.index)
        self._withhold = withhold_excluded_values
        self._unresolved: list[UnresolvedReferenceRecord] = []

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
        # Retracted resources are excluded here as well as from the clinical
        # sections. They are not "at stake in a merge" -- they are not clinical
        # facts under either outcome -- and listing their ids inside the
        # snapshot payload would leak them back into a clinician-facing view.
        resource_ids = {
            patient.id: tuple(
                r.id or ""
                for r in self.resources_for(patient.id)
                if classify(r).disposition is not Disposition.EXCLUDED
            )
            for patient in self.patients()
            if patient.id
        }
        return IdentityAnalyzer(self._issues).analyse(
            self.patients(), self._reference_counts(), resource_ids
        )

    def normalize(
        self, patient_id: str, *, as_of: datetime | None = None
    ) -> NormalizationResult | None:
        """Run one normalization pass. The application's main entry point.

        Returns None when the bundle contains no such Patient -- the caller
        turns that into a 404. Every other outcome, including a bundle where
        nothing at all is displayable, produces a result.
        """
        snapshot = self.build(patient_id, as_of=as_of)
        if snapshot is None:
            return None
        return NormalizationResult(
            snapshot=snapshot,
            excluded=snapshot.excluded,
            conflicts=self._collect_conflicts(snapshot),
            unresolved_references=tuple(self._unresolved),
            warnings=snapshot.warnings,
            issues=tuple(self._issues.all()),
        )

    def _collect_conflicts(self, snapshot: Snapshot) -> tuple[Conflict, ...]:
        """Contradictions the source left open. Surfaced, never settled."""
        conflicts: list[Conflict] = [
            Conflict(
                kind="duplicate-patient-candidate",
                summary=(
                    f"Patient records {' and '.join(candidate.member_ids)} overlap but were "
                    f"not merged (confidence: {candidate.confidence.value})."
                ),
                detail={
                    "candidateId": candidate.candidate_id,
                    "confidence": candidate.confidence.value,
                    "determination": candidate.determination.value,
                },
            )
            for candidate in snapshot.identity.candidates
            if not candidate.merge_performed
        ]
        conflicts.extend(
            Conflict(
                kind="code-system-mismatch",
                summary=coding.mismatch_reason or "Code does not validate against its system.",
                detail={"system": coding.system or "", "code": coding.code or ""},
            )
            for coding in self._mismatched_codings(snapshot)
        )
        conflicts.extend(
            Conflict(
                kind=issue.code.value,
                summary=issue.message,
                detail=issue.detail,
            )
            for issue in self._issues.all()
            if issue.code
            in (IssueCode.BDL_DUPLICATE_RESOURCE_ID, IssueCode.BDL_DUPLICATE_FULLURL)
        )
        return tuple(conflicts)

    @staticmethod
    def _mismatched_codings(snapshot: Snapshot) -> list[ResolvedCoding]:
        codings: list[ResolvedCoding] = []
        groups: list[list[ResolvedCoding]] = [
            [c.code for c in snapshot.conditions_current + snapshot.conditions_historical],
            [a.code for a in snapshot.allergies_current + snapshot.allergies_historical],
            [m.medication for m in snapshot.medications_active + snapshot.medications_historical],
            [o.code for o in snapshot.vital_signs + snapshot.other_observations],
        ]
        for group in groups:
            codings.extend(coding for coding in group if coding.code_system_mismatch)
        return codings

    def build(self, patient_id: str, *, as_of: datetime | None = None) -> Snapshot | None:
        """Assemble one patient's snapshot, or None if no such Patient exists."""
        patient = next((p for p in self.patients() if p.id == patient_id), None)
        if patient is None:
            return None

        as_of = as_of or datetime.now(UTC)
        identity = self.analyse_identity()
        candidate = identity.candidate_for(patient_id)
        classified = [(r, classify(r)) for r in self.resources_for(patient_id)]

        sections = _Sections()
        for resource, classification in classified:
            self._route(resource, classification, sections)

        # An unreconciled duplicate's active medications are disclosed with an
        # attribution rather than merged in or hidden. See identity.py.
        cross_record = self._build_cross_record_medications(patient_id, candidate, identity)
        sections.medications_active.extend(cross_record)

        self._check_bundle_reference_scheme()
        self._check_us_core(patient)

        latest = self._latest_activity(classified)
        return self._assemble(
            patient=patient,
            sections=sections,
            classified=classified,
            identity=identity,
            warnings=self._build_warnings(candidate, identity, cross_record, latest, as_of),
            latest=latest,
            as_of=as_of,
        )

    # -- routing -----------------------------------------------------------

    def _route(
        self,
        resource: DomainResource,
        classification: Classification,
        sections: _Sections,
    ) -> None:
        """Send one classified resource to exactly one destination.

        Every branch appends somewhere. Conservation -- that each bundle entry
        lands in precisely one section -- is asserted by the safety suite.
        """
        if classification.disposition is Disposition.EXCLUDED:
            sections.excluded.append(self._build_excluded(resource, classification))
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
            return

        if classification.disposition is Disposition.NEEDS_REVIEW:
            sections.needs_review.append(
                self._build_needs_review(resource, (classification.reason or "",))
            )
            return

        current = classification.disposition is Disposition.CURRENT

        # Explicit branches rather than a shared `target` local: the buckets
        # hold different view types, and a reused name would let a mis-routed
        # append past the type checker.
        if isinstance(resource, Condition):
            condition = self._build_condition(resource, classification)
            if current:
                sections.conditions_current.append(condition)
            else:
                sections.conditions_historical.append(condition)
        elif isinstance(resource, MedicationRequest):
            medication = self._build_medication(resource, classification)
            if current:
                sections.medications_active.append(medication)
            else:
                sections.medications_historical.append(medication)
        elif isinstance(resource, AllergyIntolerance):
            allergy = self._build_allergy(resource, classification)
            if current:
                sections.allergies_current.append(allergy)
            else:
                sections.allergies_historical.append(allergy)
        elif isinstance(resource, Encounter):
            sections.encounters.append(self._build_encounter(resource, classification))
        elif isinstance(resource, Observation):
            self._route_observation(resource, classification, sections)

    def _route_observation(
        self,
        observation: Observation,
        classification: Classification,
        sections: _Sections,
    ) -> None:
        """Place an Observation, or withhold it if it cannot be identified.

        The rule lives in `renderability.py`; this only acts on the verdict.
        """
        view = self._build_observation(observation, classification)
        verdict = assess_observation(view)
        if not verdict.renderable:
            sections.needs_review.append(
                self._build_needs_review(observation, verdict.reasons, view)
            )
        elif view.category_declared == VITAL_SIGNS_CATEGORY:
            sections.vital_signs.append(view)
        else:
            sections.other_observations.append(view)

    # -- final assembly ----------------------------------------------------

    def _assemble(
        self,
        *,
        patient: Patient,
        sections: _Sections,
        classified: list[tuple[DomainResource, Classification]],
        identity: IdentityAnalysis,
        warnings: list[Warning_],
        latest: PartialDate | None,
        as_of: datetime,
    ) -> Snapshot:
        """Order each section and freeze the result.

        Ordering is most-recent-first throughout, except allergies, which lead
        with the most actionable (see `safety.allergy_prominence`).
        """
        return Snapshot(
            meta=self._build_meta(patient.id or "", latest, as_of),
            patient=self.build_patient_view(patient),
            warnings=tuple(warnings),
            conditions_current=tuple(
                self._by_recency(sections.conditions_current, lambda c: c.onset)
            ),
            conditions_historical=tuple(
                self._by_recency(sections.conditions_historical, lambda c: c.onset)
            ),
            conditions_category_declared=any(
                r.category for r, _ in classified if isinstance(r, Condition)
            ),
            medications_active=tuple(
                self._by_recency(sections.medications_active, lambda m: m.authored_on)
            ),
            medications_historical=tuple(
                self._by_recency(sections.medications_historical, lambda m: m.authored_on)
            ),
            allergies_current=tuple(
                self._by_prominence(
                    self._by_recency(sections.allergies_current, lambda a: a.recorded_date),
                    classified,
                )
            ),
            allergies_historical=tuple(
                self._by_recency(sections.allergies_historical, lambda a: a.recorded_date)
            ),
            vital_signs=tuple(self._by_recency(sections.vital_signs, lambda o: o.effective)),
            other_observations=tuple(
                self._by_recency(sections.other_observations, lambda o: o.effective)
            ),
            encounters=tuple(self._by_recency(sections.encounters, lambda e: e.period_start)),
            needs_review=tuple(sections.needs_review),
            excluded=tuple(sections.excluded),
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
        """Resources whose subject is this patient, and only this one.

        Delegated to the index because it is a purely structural question, and
        because scoping is consulted repeatedly -- routing it through the
        resolver would report the same reference many times over.

        The scope boundary is enforced here and asserted by the safety suite:
        no resource belonging to another Patient record enters a snapshot
        except through the explicit attribution path.
        """
        patient = next((p for p in self.patients() if p.id == patient_id), None)
        if patient is None:
            return []
        return [r for r in self._loaded.index.for_patient(patient) if not isinstance(r, Patient)]

    # -- builders ----------------------------------------------------------

    def _coding(
        self, concept: CodeableConcept | None, resource: DomainResource, path: str
    ) -> ResolvedCoding:
        """The coding a section renders.

        Additional codings are translations of the same concept; they are
        resolved and reported but not rendered, because choosing between two
        code systems for one concept is a terminology decision we cannot make.
        """
        resolved = self._terminology.resolve_concept(
            concept, source_id=resource.id, source_type=resource.resourceType, path=path
        )
        if resolved.has_alternates:
            self._issues.add(
                IssueCode.TERMINOLOGY_MULTIPLE_CODINGS,
                Severity.LOW,
                f"{resource.key} {path} carries {len(resolved.alternates) + 1} codings. "
                f"The first is rendered; the others are retained but not displayed.",
                resource_id=resource.id,
                resource_type=resource.resourceType,
                path=path,
            )
        return resolved.primary

    def _date(self, raw: str | None, resource: DomainResource, path: str) -> PartialDate | None:
        """Parse a source date, reporting reduced precision and invalid values.

        Absent and malformed both yield None to the view layer -- there is no
        date to show either way -- but only one of them is a data-quality
        problem, so they are reported differently.
        """
        parsed = PartialDate.parse(raw)
        if parsed is None:
            if raw is not None and raw.strip():
                self._issues.add(
                    IssueCode.DATE_INVALID,
                    Severity.MEDIUM,
                    f"{path} is '{raw}', which is not a valid FHIR date or dateTime. "
                    f"No date is shown for this record rather than a guessed one.",
                    resource_id=resource.id,
                    resource_type=resource.resourceType,
                    path=path,
                    detail={"value": raw},
                )
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

    def _resolve(
        self,
        reference: Reference | None,
        *,
        source: DomainResource,
        path: str,
        expected_type: str | None = None,
    ) -> ResolutionResult | None:
        """Resolve and report. The resolver itself stays free of reporting."""
        result = self._resolver.resolve(reference, expected_type=expected_type)
        if result is None or not result.is_problem:
            return result

        self._unresolved.append(
            UnresolvedReferenceRecord(
                source_resource_id=source.id,
                source_resource_type=source.resourceType,
                path=path,
                reference=result.reference,
                status=result.status.value,
                reason=result.reason.value if result.reason else None,
            )
        )
        code, severity = _RESOLUTION_ISSUES[result.status]
        self._issues.add(
            code,
            severity,
            result.detail or f"Reference '{result.reference}' could not be used.",
            resource_id=source.id,
            resource_type=source.resourceType,
            path=path,
            detail={
                "target": result.reference,
                "reason": result.reason.value if result.reason else "",
                "expectedType": result.expected_type or "",
                "actualType": result.actual_type or "",
            },
        )
        return result

    def _ref_view(self, resolved: ResolutionResult | None) -> ReferenceView | None:
        if resolved is None:
            return None
        display = self._label_for(resolved.target) if resolved.target is not None else None
        return ReferenceView(
            reference=resolved.reference,
            resolved=resolved.resolved,
            display=display,
            reason=resolved.reason.value if resolved.reason else None,
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
                self._resolve(
                    condition.encounter,
                    source=condition,
                    path="Condition.encounter",
                    expected_type="Encounter",
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
            # Observation.performer legally targets Practitioner,
            # PractitionerRole, Organization, CareTeam, Patient or RelatedPerson,
            # so no expected type is asserted here.
            performer=self._ref_view(
                self._resolve(
                    observation.performer[0] if observation.performer else None,
                    source=observation,
                    path="Observation.performer[0]",
                )
            ),
            encounter=self._ref_view(
                self._resolve(
                    observation.encounter,
                    source=observation,
                    path="Observation.encounter",
                    expected_type="Encounter",
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
            suppression_reason=c.exclusion_reason or ExclusionReason.ENTERED_IN_ERROR,
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
                if i.system not in SUPPRESSED_IDENTIFIER_SYSTEMS
            ),
            withheld_identifier_count=sum(
                1 for i in patient.identifier if i.system in SUPPRESSED_IDENTIFIER_SYSTEMS
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
    def _by_prominence(
        allergies: list[AllergyView],
        classified: list[tuple[DomainResource, Classification]],
    ) -> list[AllergyView]:
        """Stable re-sort so confirmed high-criticality allergies lead.

        Applied after the recency sort, so items of equal prominence keep their
        recency order.
        """
        sources = {
            resource.id: resource
            for resource, _ in classified
            if isinstance(resource, AllergyIntolerance)
        }
        return sorted(
            allergies,
            key=lambda view: allergy_prominence(sources[view.id])
            if view.id in sources
            else (4, 1),
        )

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
