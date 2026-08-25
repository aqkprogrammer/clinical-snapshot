"""ReferenceResolver: four outcomes, no fabrication, original string preserved.

The distinction the tests protect is between "the source recorded nothing"
(`None`), "the source pointed at something missing" (`UNRESOLVED`), "the source
pointed at the wrong kind of thing" (`TYPE_MISMATCH`), and "the source wrote
something unusable" (`MALFORMED`). Collapsing any of these into the others
loses information a reader needs.
"""

from __future__ import annotations

import pytest

from clinical_snapshot.fhir.index import BundleIndex
from clinical_snapshot.fhir.models import Encounter, Observation, Patient, Reference
from clinical_snapshot.fhir.resolver import (
    ReferenceKind,
    ReferenceResolver,
    ResolutionMethod,
    ResolutionReason,
    ResolutionStatus,
    parse_reference,
)


@pytest.fixture
def resolver() -> ReferenceResolver:
    index = BundleIndex()
    index.add(Patient(id="patient-001"), "urn:uuid:patient-001")
    index.add(Encounter(id="encounter-001", status="finished"), "urn:uuid:encounter-001")
    index.add(Observation(id="observation-001", status="final"), "urn:uuid:observation-001")
    return ReferenceResolver(index)


class TestValidReference:
    def test_resolves_an_existing_resource(self, resolver: ReferenceResolver) -> None:
        result = resolver.resolve("Patient/patient-001")
        assert result is not None
        assert result.status is ResolutionStatus.RESOLVED
        assert result.resolved is True
        assert result.target is not None
        assert result.target.id == "patient-001"

    def test_resolves_an_encounter(self, resolver: ReferenceResolver) -> None:
        result = resolver.resolve("Encounter/encounter-001")
        assert result is not None and result.resolved

    def test_accepts_a_reference_object_as_well_as_a_string(
        self, resolver: ReferenceResolver
    ) -> None:
        result = resolver.resolve(Reference(reference="Patient/patient-001"))
        assert result is not None and result.resolved

    def test_full_url_matching_takes_precedence_over_the_fallback(
        self, resolver: ReferenceResolver
    ) -> None:
        result = resolver.resolve("urn:uuid:patient-001")
        assert result is not None
        assert result.method is ResolutionMethod.FULL_URL

    def test_relative_reference_uses_the_documented_type_id_fallback(
        self, resolver: ReferenceResolver
    ) -> None:
        result = resolver.resolve("Patient/patient-001")
        assert result is not None
        assert result.method is ResolutionMethod.TYPE_ID
        assert resolver.used_type_id_fallback is True

    def test_fallback_flag_stays_false_until_the_fallback_is_used(
        self, resolver: ReferenceResolver
    ) -> None:
        assert resolver.used_type_id_fallback is False
        resolver.resolve("urn:uuid:patient-001")
        assert resolver.used_type_id_fallback is False

    def test_original_reference_string_is_preserved(self, resolver: ReferenceResolver) -> None:
        result = resolver.resolve("Patient/patient-001")
        assert result is not None
        assert result.reference == "Patient/patient-001"


class TestMissingResource:
    def test_missing_encounter_is_unresolved_not_fabricated(
        self, resolver: ReferenceResolver
    ) -> None:
        result = resolver.resolve("Encounter/encounter-099")
        assert result is not None
        assert result.status is ResolutionStatus.UNRESOLVED
        assert result.target is None
        assert result.resolved is False
        assert result.reason is ResolutionReason.TARGET_NOT_IN_BUNDLE

    def test_absent_practitioner_is_unresolved(self, resolver: ReferenceResolver) -> None:
        """The bundle has no Practitioner resources at all, so this must report
        'not present' rather than silently yielding no performer."""
        result = resolver.resolve("Practitioner/practitioner-999")
        assert result is not None
        assert result.status is ResolutionStatus.UNRESOLVED
        assert result.target is None
        assert result.reference == "Practitioner/practitioner-999"
        assert "not present in the bundle" in (result.detail or "")

    def test_absent_practitioner_with_expected_type_still_unresolved(
        self, resolver: ReferenceResolver
    ) -> None:
        result = resolver.resolve("Practitioner/practitioner-999", expected_type="Practitioner")
        assert result is not None
        assert result.status is ResolutionStatus.UNRESOLVED

    def test_unresolved_results_are_structured_not_none(
        self, resolver: ReferenceResolver
    ) -> None:
        assert resolver.resolve("Encounter/encounter-099") is not None

    def test_absent_reference_returns_none(self, resolver: ReferenceResolver) -> None:
        """No reference at all is a different statement from a broken one."""
        assert resolver.resolve(None) is None
        assert resolver.resolve("") is None
        assert resolver.resolve("   ") is None
        assert resolver.resolve(Reference()) is None


class TestMalformedReference:
    @pytest.mark.parametrize(
        "reference",
        [
            "Patient",
            "Patient/",
            "/patient-001",
            "patient-001",
            "patient/patient-001",
            "Patient/pat ient",
            "Patient//patient-001",
            "::::",
            "urn:",
            "#",
        ],
    )
    def test_unusable_strings_are_malformed(
        self, resolver: ReferenceResolver, reference: str
    ) -> None:
        result = resolver.resolve(reference)
        assert result is not None
        assert result.status is ResolutionStatus.MALFORMED
        assert result.reason is ResolutionReason.MALFORMED_REFERENCE
        assert result.target is None

    def test_malformed_reference_preserves_the_original_string(
        self, resolver: ReferenceResolver
    ) -> None:
        result = resolver.resolve("Patient//patient-001")
        assert result is not None
        assert result.reference == "Patient//patient-001"

    def test_malformed_is_distinct_from_unresolved(self, resolver: ReferenceResolver) -> None:
        malformed = resolver.resolve("Patient")
        unresolved = resolver.resolve("Patient/patient-999")
        assert malformed is not None and unresolved is not None
        assert malformed.status is not unresolved.status


class TestTypeMismatch:
    def test_declared_type_conflicting_with_expectation(
        self, resolver: ReferenceResolver
    ) -> None:
        result = resolver.resolve("Patient/patient-001", expected_type="Encounter")
        assert result is not None
        assert result.status is ResolutionStatus.TYPE_MISMATCH
        assert result.expected_type == "Encounter"
        assert result.actual_type == "Patient"
        assert result.reason is ResolutionReason.TYPE_MISMATCH

    def test_mismatch_never_returns_the_wrong_target(
        self, resolver: ReferenceResolver
    ) -> None:
        """A caller that expects an Encounter must not receive a Patient."""
        result = resolver.resolve("Patient/patient-001", expected_type="Encounter")
        assert result is not None
        assert result.target is None
        assert result.resolved is False

    def test_mismatch_is_detected_even_when_the_target_is_absent(
        self, resolver: ReferenceResolver
    ) -> None:
        """The reference is wrong regardless of whether the target exists."""
        result = resolver.resolve("Patient/patient-404", expected_type="Encounter")
        assert result is not None
        assert result.status is ResolutionStatus.TYPE_MISMATCH

    def test_mismatch_detected_via_the_resolved_target_for_urn_references(
        self, resolver: ReferenceResolver
    ) -> None:
        """A URN declares no type, so the mismatch only surfaces after lookup."""
        result = resolver.resolve("urn:uuid:patient-001", expected_type="Encounter")
        assert result is not None
        assert result.status is ResolutionStatus.TYPE_MISMATCH
        assert result.actual_type == "Patient"
        assert result.target is None

    def test_matching_expected_type_resolves_normally(
        self, resolver: ReferenceResolver
    ) -> None:
        result = resolver.resolve("Encounter/encounter-001", expected_type="Encounter")
        assert result is not None and result.resolved

    def test_no_expected_type_never_reports_a_mismatch(
        self, resolver: ReferenceResolver
    ) -> None:
        result = resolver.resolve("Patient/patient-001")
        assert result is not None
        assert result.status is ResolutionStatus.RESOLVED


class TestContainedReferences:
    def test_fragment_is_unresolved_with_a_specific_reason(
        self, resolver: ReferenceResolver
    ) -> None:
        result = resolver.resolve("#contained-med")
        assert result is not None
        assert result.status is ResolutionStatus.UNRESOLVED
        assert result.reason is ResolutionReason.CONTAINED_UNSUPPORTED
        assert result.reference == "#contained-med"


class TestParsing:
    @pytest.mark.parametrize(
        ("reference", "kind", "resource_type", "resource_id"),
        [
            ("Patient/patient-001", ReferenceKind.RELATIVE, "Patient", "patient-001"),
            (
                "http://ehr.example.org/fhir/Patient/patient-001",
                ReferenceKind.ABSOLUTE,
                "Patient",
                "patient-001",
            ),
            (
                "https://ehr.example.org/fhir/Encounter/e1/_history/3",
                ReferenceKind.ABSOLUTE,
                "Encounter",
                "e1",
            ),
            ("urn:uuid:patient-001", ReferenceKind.URN, None, None),
            ("#inline", ReferenceKind.FRAGMENT, None, "inline"),
        ],
    )
    def test_recognises_each_addressing_form(
        self,
        reference: str,
        kind: ReferenceKind,
        resource_type: str | None,
        resource_id: str | None,
    ) -> None:
        parsed = parse_reference(reference)
        assert parsed is not None
        assert parsed.kind is kind
        assert parsed.resource_type == resource_type
        assert parsed.resource_id == resource_id
        assert parsed.raw == reference

    def test_absolute_url_resolves_against_the_index(
        self, resolver: ReferenceResolver
    ) -> None:
        result = resolver.resolve("http://ehr.example.org/fhir/Patient/patient-001")
        assert result is not None
        assert result.resolved is True
        assert result.method is ResolutionMethod.TYPE_ID


class TestPurity:
    def test_resolution_is_deterministic(self, resolver: ReferenceResolver) -> None:
        results = [resolver.resolve("Encounter/encounter-099") for _ in range(20)]
        assert all(r is not None and r.status is results[0].status for r in results)  # type: ignore[union-attr]

    def test_resolver_never_mutates_the_index(self, resolver: ReferenceResolver) -> None:
        resolver.resolve("Encounter/encounter-099")
        resolver.resolve("Practitioner/practitioner-999")
        resolver.resolve("Patient/patient-001")
        assert resolver.resolve("Encounter/encounter-099") is not None
        assert resolver.resolve("Practitioner/practitioner-999") is not None
