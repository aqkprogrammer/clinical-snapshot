"""Bundle loading and lenient Pydantic validation.

Leniency is the point: a resource we cannot parse must degrade itself and be
reported, never take the bundle down and never vanish from the tally.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from clinical_snapshot.domain.issues import IssueCode
from clinical_snapshot.fhir.loader import load_bundle
from clinical_snapshot.fhir.models import Observation, Patient


def write(tmp_path: Path, bundle: dict[str, object]) -> Path:
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps(bundle), encoding="utf-8")
    return path


def collection(*resources: dict[str, object]) -> dict[str, object]:
    return {
        "resourceType": "Bundle",
        "id": "test",
        "type": "collection",
        "entry": [{"fullUrl": f"urn:uuid:e{i}", "resource": r} for i, r in enumerate(resources)],
    }


class TestSuppliedBundle:
    def test_parses_every_entry(self, bundle_path: Path) -> None:
        loaded = load_bundle(bundle_path)
        assert loaded.entry_count == 17
        assert len(loaded.index) == 17
        assert loaded.unparsed_entry_count == 0

    def test_models_are_typed_not_generic_dicts(self, bundle_path: Path) -> None:
        loaded = load_bundle(bundle_path)
        assert all(isinstance(p, Patient) for p in loaded.index.of_type("Patient"))
        assert all(isinstance(o, Observation) for o in loaded.index.of_type("Observation"))

    def test_detects_the_structural_defects(self, bundle_path: Path) -> None:
        codes = {i.code for i in load_bundle(bundle_path).issues.all()}
        assert IssueCode.BDL_TOTAL_ON_COLLECTION in codes
        assert IssueCode.BDL_INVALID_UUID in codes
        assert IssueCode.BDL_NO_PROVENANCE in codes


class TestLenientValidation:
    def test_unknown_fields_are_preserved_not_discarded(self, tmp_path: Path) -> None:
        path = write(
            tmp_path,
            collection(
                {
                    "resourceType": "Observation",
                    "id": "o1",
                    "status": "final",
                    "someFutureElement": {"nested": True},
                }
            ),
        )
        observation = load_bundle(path).index.get("Observation", "o1")
        assert observation is not None
        assert observation.model_extra is not None
        assert "someFutureElement" in observation.model_extra

    def test_missing_optional_elements_do_not_fail_validation(self, tmp_path: Path) -> None:
        path = write(tmp_path, collection({"resourceType": "Condition", "id": "c1"}))
        loaded = load_bundle(path)
        assert loaded.unparsed_entry_count == 0
        assert loaded.index.get("Condition", "c1") is not None

    def test_a_resource_that_fails_validation_is_excluded_and_reported(
        self, tmp_path: Path
    ) -> None:
        """A wrongly-typed element degrades one resource, not the bundle."""
        path = write(
            tmp_path,
            collection(
                {"resourceType": "Observation", "id": "good", "status": "final"},
                {"resourceType": "Observation", "id": "bad", "status": "final", "component": 7},
            ),
        )
        loaded = load_bundle(path)
        assert loaded.unparsed_entry_count == 1
        assert loaded.index.get("Observation", "good") is not None
        assert loaded.index.get("Observation", "bad") is None
        assert loaded.issues.with_code(IssueCode.RESOURCE_UNPARSEABLE)

    def test_unsupported_resource_type_is_retained_and_reported(self, tmp_path: Path) -> None:
        """It still counts toward the entry tally rather than disappearing."""
        path = write(tmp_path, collection({"resourceType": "Procedure", "id": "p1"}))
        loaded = load_bundle(path)
        assert len(loaded.index) == 1
        assert loaded.index.of_type("Procedure")
        assert loaded.issues.with_code(IssueCode.RESOURCE_TYPE_UNSUPPORTED)

    def test_entry_with_no_resource_is_reported(self, tmp_path: Path) -> None:
        path = write(
            tmp_path,
            {"resourceType": "Bundle", "type": "collection", "entry": [{"fullUrl": "urn:uuid:x"}]},
        )
        loaded = load_bundle(path)
        assert loaded.unparsed_entry_count == 1
        assert loaded.issues.with_code(IssueCode.RESOURCE_UNPARSEABLE)

    def test_entry_with_no_resource_type_is_reported(self, tmp_path: Path) -> None:
        path = write(tmp_path, collection({"id": "mystery"}))
        loaded = load_bundle(path)
        assert loaded.unparsed_entry_count == 1
        assert loaded.issues.with_code(IssueCode.RESOURCE_UNPARSEABLE)


class TestStructuralChecks:
    def test_entry_count_mismatch_is_reported(self, tmp_path: Path) -> None:
        bundle = collection({"resourceType": "Patient", "id": "p1"})
        bundle["total"] = 9
        loaded = load_bundle(write(tmp_path, bundle))
        assert loaded.issues.with_code(IssueCode.BDL_ENTRY_COUNT_MISMATCH)

    def test_duplicate_resource_ids_are_reported_not_silently_dropped(
        self, tmp_path: Path
    ) -> None:
        path = write(
            tmp_path,
            collection(
                {"resourceType": "Observation", "id": "dup", "status": "final"},
                {"resourceType": "Observation", "id": "dup", "status": "final"},
            ),
        )
        loaded = load_bundle(path)
        assert len(loaded.index) == 2
        assert loaded.issues.with_code(IssueCode.BDL_DUPLICATE_RESOURCE_ID)

    def test_missing_resource_id_is_reported(self, tmp_path: Path) -> None:
        path = write(tmp_path, collection({"resourceType": "Observation", "status": "final"}))
        loaded = load_bundle(path)
        assert loaded.issues.with_code(IssueCode.RESOURCE_ID_MISSING)

    def test_valid_uuid_full_urls_raise_no_uuid_issue(self, tmp_path: Path) -> None:
        path = write(
            tmp_path,
            {
                "resourceType": "Bundle",
                "type": "collection",
                "entry": [
                    {
                        "fullUrl": "urn:uuid:3f2504e0-4f89-41d3-9a0c-0305e82c3301",
                        "resource": {"resourceType": "Patient", "id": "p1"},
                    }
                ],
            },
        )
        assert not load_bundle(path).issues.with_code(IssueCode.BDL_INVALID_UUID)

    def test_empty_bundle_loads_cleanly(self, tmp_path: Path) -> None:
        loaded = load_bundle(write(tmp_path, {"resourceType": "Bundle", "type": "collection"}))
        assert loaded.entry_count == 0
        assert len(loaded.index) == 0

    def test_a_missing_file_raises_rather_than_returning_an_empty_bundle(
        self, tmp_path: Path
    ) -> None:
        with pytest.raises(FileNotFoundError):
            load_bundle(tmp_path / "nope.json")
