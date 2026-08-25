"""BundleIndex: addressing, conflicts, and the refusal to overwrite.

The property that matters most here is that a duplicate never makes its
predecessor -- or itself -- disappear. An overwritten resource is invisible,
and invisible is indistinguishable from absent to whoever reads the output.
"""

from __future__ import annotations

import pytest

from clinical_snapshot.fhir.index import BundleIndex, IndexConflictKind
from clinical_snapshot.fhir.models import (
    Condition,
    Encounter,
    Observation,
    Patient,
    Reference,
)


def observation(obs_id: str | None, subject: str | None = None) -> Observation:
    return Observation(
        id=obs_id,
        status="final",
        subject=Reference(reference=subject) if subject else None,
    )


@pytest.fixture
def index() -> BundleIndex:
    index = BundleIndex()
    index.add(Patient(id="patient-001"), "urn:uuid:patient-001")
    index.add(Patient(id="patient-002"), "urn:uuid:patient-002")
    index.add(Encounter(id="encounter-001", status="finished"), "urn:uuid:encounter-001")
    index.add(observation("observation-001", "Patient/patient-001"), "urn:uuid:observation-001")
    index.add(observation("observation-002", "Patient/patient-001"), "urn:uuid:observation-002")
    index.add(observation("observation-003", "Patient/patient-002"), "urn:uuid:observation-003")
    return index


class TestAddressing:
    def test_get_by_type_and_id(self, index: BundleIndex) -> None:
        found = index.get("Observation", "observation-002")
        assert found is not None
        assert found.id == "observation-002"

    def test_get_by_key(self, index: BundleIndex) -> None:
        assert index.get_by_key("Encounter/encounter-001") is not None

    def test_get_by_full_url(self, index: BundleIndex) -> None:
        assert index.get_by_full_url("urn:uuid:encounter-001") is not None

    def test_unknown_address_returns_none_rather_than_raising(self, index: BundleIndex) -> None:
        assert index.get("Encounter", "encounter-099") is None
        assert index.get_by_key("Practitioner/practitioner-999") is None
        assert index.get_by_full_url("urn:uuid:nope") is None

    def test_of_type_preserves_bundle_order(self, index: BundleIndex) -> None:
        assert [r.id for r in index.of_type("Observation")] == [
            "observation-001",
            "observation-002",
            "observation-003",
        ]

    def test_of_type_for_absent_type_is_empty(self, index: BundleIndex) -> None:
        assert index.of_type("Practitioner") == []

    def test_patients_returns_only_patients(self, index: BundleIndex) -> None:
        patients = index.patients()
        assert [p.id for p in patients] == ["patient-001", "patient-002"]
        assert all(isinstance(p, Patient) for p in patients)

    def test_membership_and_length(self, index: BundleIndex) -> None:
        assert len(index) == 6
        assert "Patient/patient-001" in index
        assert "Patient/nope" not in index
        assert 42 not in index


class TestPatientAssociation:
    def test_resources_are_grouped_by_subject(self, index: BundleIndex) -> None:
        found = index.for_patient_reference("Patient/patient-001")
        assert [r.id for r in found] == ["observation-001", "observation-002"]

    def test_association_works_through_the_full_url_alias(self, index: BundleIndex) -> None:
        """References use the relative form while entries are addressed by URN;
        both name the same resource."""
        assert index.for_patient_reference("urn:uuid:patient-001") == index.for_patient_reference(
            "Patient/patient-001"
        )

    def test_for_patient_takes_the_resource(self, index: BundleIndex) -> None:
        patient = index.get("Patient", "patient-002")
        assert isinstance(patient, Patient)
        assert [r.id for r in index.for_patient(patient)] == ["observation-003"]

    def test_patient_with_no_associated_resources(self) -> None:
        index = BundleIndex()
        patient = Patient(id="lonely")
        index.add(patient, "urn:uuid:lonely")
        assert index.for_patient(patient) == []

    def test_unknown_reference_yields_nothing_rather_than_everything(
        self, index: BundleIndex
    ) -> None:
        assert index.for_patient_reference("Patient/does-not-exist") == []

    def test_results_are_deterministic_across_repeated_calls(self, index: BundleIndex) -> None:
        first = [r.id for r in index.for_patient_reference("Patient/patient-001")]
        for _ in range(25):
            assert [r.id for r in index.for_patient_reference("Patient/patient-001")] == first


class TestDuplicateIds:
    @pytest.fixture
    def duplicated(self) -> BundleIndex:
        index = BundleIndex()
        index.add(observation("observation-001", "Patient/patient-001"), "urn:uuid:first")
        index.add(Encounter(id="encounter-001", status="finished"), "urn:uuid:encounter-001")
        index.add(observation("observation-001", "Patient/patient-002"), "urn:uuid:second")
        return index

    def test_neither_duplicate_is_discarded(self, duplicated: BundleIndex) -> None:
        assert len(duplicated) == 3
        assert len(duplicated.of_type("Observation")) == 2

    def test_first_occurrence_answers_lookups(self, duplicated: BundleIndex) -> None:
        found = duplicated.get("Observation", "observation-001")
        assert found is not None
        assert found.subject is not None
        assert found.subject.reference == "Patient/patient-001"

    def test_both_candidates_remain_reachable(self, duplicated: BundleIndex) -> None:
        candidates = duplicated.candidates("Observation/observation-001")
        assert len(candidates) == 2
        subjects = [c.subject.reference for c in candidates if c.subject]
        assert subjects == ["Patient/patient-001", "Patient/patient-002"]

    def test_conflict_is_reported_not_silently_resolved(self, duplicated: BundleIndex) -> None:
        conflicts = duplicated.report().of_kind(IndexConflictKind.DUPLICATE_KEY)
        assert len(conflicts) == 1
        conflict = conflicts[0]
        assert conflict.key == "Observation/observation-001"
        assert conflict.positions == (0, 2)
        assert conflict.retained_position == 0
        assert conflict.shadowed_positions == (2,)

    def test_shadowed_copy_is_still_reachable_by_its_own_full_url(
        self, duplicated: BundleIndex
    ) -> None:
        assert duplicated.get_by_full_url("urn:uuid:second") is not None

    def test_report_is_deterministic(self, duplicated: BundleIndex) -> None:
        first = duplicated.report()
        for _ in range(10):
            assert duplicated.report() == first


class TestDuplicateFullUrls:
    def test_duplicate_full_url_is_reported(self) -> None:
        index = BundleIndex()
        index.add(observation("observation-001"), "urn:uuid:same")
        index.add(observation("observation-002"), "urn:uuid:same")
        conflicts = index.report().of_kind(IndexConflictKind.DUPLICATE_FULL_URL)
        assert len(conflicts) == 1
        assert conflicts[0].full_url == "urn:uuid:same"
        assert conflicts[0].retained_position == 0

    def test_both_remain_addressable_by_their_distinct_ids(self) -> None:
        index = BundleIndex()
        index.add(observation("observation-001"), "urn:uuid:same")
        index.add(observation("observation-002"), "urn:uuid:same")
        assert index.get("Observation", "observation-001") is not None
        assert index.get("Observation", "observation-002") is not None


class TestMissingIds:
    def test_resource_without_id_does_not_crash_the_index(self) -> None:
        index = BundleIndex()
        entry = index.add(observation(None), "urn:uuid:anonymous")
        assert entry.key is None
        assert len(index) == 1

    def test_resource_without_id_is_still_listed(self) -> None:
        index = BundleIndex()
        index.add(observation(None))
        assert len(index.of_type("Observation")) == 1
        assert len(index.all()) == 1

    def test_missing_id_is_reported_as_a_conflict(self) -> None:
        index = BundleIndex()
        index.add(observation(None))
        conflicts = index.report().of_kind(IndexConflictKind.MISSING_ID)
        assert len(conflicts) == 1
        assert conflicts[0].retained_position is None
        assert conflicts[0].resource_type == "Observation"

    def test_missing_id_is_excluded_from_addressable_count(self) -> None:
        index = BundleIndex()
        index.add(observation("observation-001"))
        index.add(observation(None))
        report = index.report()
        assert report.indexed_count == 2
        assert report.addressable_count == 1


class TestReport:
    def test_a_clean_bundle_reports_no_conflicts(self, index: BundleIndex) -> None:
        report = index.report()
        assert report.has_conflicts is False
        assert report.indexed_count == 6
        assert report.addressable_count == 6

    def test_build_indexes_pairs_in_order(self) -> None:
        index = BundleIndex.build(
            [
                (Patient(id="patient-001"), "urn:uuid:patient-001"),
                (Condition(id="condition-001"), None),
            ]
        )
        assert len(index) == 2
        assert index.resource_types() == ["Condition", "Patient"]
        assert [e.position for e in index.entries()] == [0, 1]


class TestNoClinicalAssumptions:
    def test_retracted_resources_are_indexed_like_any_other(self) -> None:
        """The index is structural. Deciding a resource is unsafe to show is
        the safety policy's job, not the index's."""
        index = BundleIndex()
        index.add(observation("observation-004", "Patient/patient-001"))
        retracted = Observation(
            id="observation-005",
            status="entered-in-error",
            subject=Reference(reference="Patient/patient-001"),
        )
        index.add(retracted)
        assert len(index.of_type("Observation")) == 2
        assert index.get("Observation", "observation-005") is not None
        assert len(index.for_patient_reference("Patient/patient-001")) == 2
