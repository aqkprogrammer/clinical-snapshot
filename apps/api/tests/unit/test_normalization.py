"""NormalizationResult against the actual supplied bundle.

These assert the shape of one full pass: what is displayable, what was
withheld, what conflicts survived, and that the pass is deterministic.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from clinical_snapshot.domain.assembler import SnapshotAssembler
from clinical_snapshot.domain.snapshot import NormalizationResult
from clinical_snapshot.fhir.loader import load_bundle

AS_OF = datetime(2026, 8, 25, tzinfo=UTC)


def normalize(bundle_path: Path, patient_id: str = "patient-001") -> NormalizationResult:
    result = SnapshotAssembler(load_bundle(bundle_path)).normalize(patient_id, as_of=AS_OF)
    assert result is not None
    return result


@pytest.fixture
def result(bundle_path: Path) -> NormalizationResult:
    return normalize(bundle_path)


class TestStructure:
    def test_carries_the_snapshot_and_everything_decided_along_the_way(
        self, result: NormalizationResult
    ) -> None:
        assert result.snapshot is not None
        assert result.excluded
        assert result.conflicts
        assert result.unresolved_references
        assert result.warnings
        assert result.issues

    def test_the_supplied_bundle_is_not_clean(self, result: NormalizationResult) -> None:
        assert result.is_clean is False

    def test_unknown_patient_yields_none(self, bundle_path: Path) -> None:
        assembler = SnapshotAssembler(load_bundle(bundle_path))
        assert assembler.normalize("patient-999") is None


class TestExcluded:
    def test_all_four_retracted_resources_are_withheld(
        self, result: NormalizationResult
    ) -> None:
        assert {e.id for e in result.excluded} == {
            "observation-004",
            "condition-002",
            "allergyintolerance-002",
            "encounter-002",
        }

    def test_each_exclusion_is_traceable_to_a_field_and_a_reason(
        self, result: NormalizationResult
    ) -> None:
        for excluded in result.excluded:
            assert excluded.suppression_reason
            assert excluded.suppression_field
            assert excluded.resource_type

    def test_the_retracted_lab_value_is_withheld(self, result: NormalizationResult) -> None:
        creatinine = next(e for e in result.excluded if e.id == "observation-004")
        assert creatinine.value_withheld is True
        assert creatinine.value_withheld_reason


class TestUnresolvedReferences:
    def test_both_dangling_references_are_recorded(
        self, result: NormalizationResult
    ) -> None:
        assert {r.reference for r in result.unresolved_references} == {
            "Encounter/encounter-099",
            "Practitioner/practitioner-999",
        }

    def test_each_record_names_its_source_element(self, result: NormalizationResult) -> None:
        by_reference = {r.reference: r for r in result.unresolved_references}
        assert by_reference["Encounter/encounter-099"].path == "Condition.encounter"
        assert by_reference["Encounter/encounter-099"].source_resource_id == "condition-003"
        assert by_reference["Practitioner/practitioner-999"].path == "Observation.performer[0]"

    def test_status_and_reason_are_preserved(self, result: NormalizationResult) -> None:
        for record in result.unresolved_references:
            assert record.status == "unresolved"
            assert record.reason == "REFERENCE_TARGET_NOT_IN_BUNDLE"


class TestConflicts:
    def test_the_unreconciled_duplicate_is_a_conflict(
        self, result: NormalizationResult
    ) -> None:
        kinds = {c.kind for c in result.conflicts}
        assert "duplicate-patient-candidate" in kinds

    def test_the_code_system_mismatch_is_a_conflict(
        self, result: NormalizationResult
    ) -> None:
        kinds = {c.kind for c in result.conflicts}
        assert "code-system-mismatch" in kinds

    def test_conflicts_carry_enough_detail_to_investigate(
        self, result: NormalizationResult
    ) -> None:
        duplicate = next(c for c in result.conflicts if c.kind == "duplicate-patient-candidate")
        assert duplicate.detail["confidence"] == "conflicted"
        assert duplicate.detail["candidateId"]


class TestSnapshotContent:
    def test_displayable_sections_match_the_bundle(self, result: NormalizationResult) -> None:
        snapshot = result.snapshot
        assert {c.id for c in snapshot.conditions_current} == {"condition-001", "condition-003"}
        assert {m.id for m in snapshot.medications_historical} == {"medicationrequest-002"}
        assert {a.id for a in snapshot.allergies_current} == {
            "allergyintolerance-001",
            "allergyintolerance-003",
        }
        assert {o.id for o in snapshot.vital_signs} == {"observation-001"}
        assert {o.id for o in snapshot.other_observations} == {"observation-003"}
        assert {e.id for e in snapshot.encounters} == {"encounter-001"}
        assert {n.id for n in snapshot.needs_review} == {"observation-002"}

    def test_the_duplicate_records_medication_is_attributed_not_absorbed(
        self, result: NormalizationResult
    ) -> None:
        active = {m.id: m for m in result.snapshot.medications_active}
        assert active["medicationrequest-001"].attribution is None
        assert active["medicationrequest-003"].attribution is not None

    def test_no_patient_records_were_merged(self, result: NormalizationResult) -> None:
        assert all(not c.merge_performed for c in result.snapshot.identity.candidates)

    def test_national_identifier_is_not_present_in_the_read_model(
        self, result: NormalizationResult
    ) -> None:
        systems = {i.system for i in result.snapshot.patient.identifiers}
        assert "http://hl7.org/fhir/sid/us-ssn" not in systems
        assert result.snapshot.patient.withheld_identifier_count == 1

    def test_every_displayed_item_carries_provenance(
        self, result: NormalizationResult
    ) -> None:
        snapshot = result.snapshot
        items = [
            *snapshot.conditions_current, *snapshot.conditions_historical,
            *snapshot.medications_active, *snapshot.medications_historical,
            *snapshot.allergies_current, *snapshot.vital_signs,
            *snapshot.other_observations, *snapshot.encounters,
        ]
        assert items
        for item in items:
            assert item.provenance.resource_id
            assert item.provenance.admitted_by.startswith("RULE_")


class TestDeterminism:
    def test_repeated_passes_are_identical(self, bundle_path: Path) -> None:
        first = normalize(bundle_path)
        for _ in range(5):
            again = normalize(bundle_path)
            assert again.snapshot == first.snapshot
            assert again.excluded == first.excluded
            assert again.conflicts == first.conflicts
            assert again.unresolved_references == first.unresolved_references

    def test_a_fixed_as_of_produces_a_fixed_staleness(self, bundle_path: Path) -> None:
        assert normalize(bundle_path).snapshot.meta.days_since_latest_activity == 293
