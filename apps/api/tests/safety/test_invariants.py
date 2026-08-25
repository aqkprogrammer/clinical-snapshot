"""Properties that must hold for ANY bundle, not just the supplied one.

These are the tests that matter. Everything else checks that a function does
what it says; these check that the application cannot do the specific harmful
things this data is designed to provoke.

They run against the serialized HTTP payload rather than the domain objects,
because the payload is what a clinician's browser actually receives.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.conftest import FIXTURES, client_for, objects, walk

RETRACTED_IDS = {"observation-004", "condition-002", "allergyintolerance-002", "encounter-002"}
RETRACTED_CREATININE_VALUE = 14.7


@pytest.fixture(scope="module")
def snapshot(request: pytest.FixtureRequest) -> dict[str, Any]:
    from tests.conftest import BUNDLE_PATH

    return client_for(BUNDLE_PATH).get("/api/v1/patients/patient-001/snapshot").json()


@pytest.fixture(scope="module")
def excluded(request: pytest.FixtureRequest) -> dict[str, Any]:
    from tests.conftest import BUNDLE_PATH

    return client_for(BUNDLE_PATH).get("/api/v1/patients/patient-001/excluded").json()


def codings(document: Any) -> list[dict[str, Any]]:
    return list(objects(document, lambda d: "displayStatus" in d))


def dates(document: Any) -> list[dict[str, Any]]:
    return list(objects(document, lambda d: set(d) == {"value", "precision"}))


# ---------------------------------------------------------------------------
# 1. Retracted resources never reach a clinical section
# ---------------------------------------------------------------------------


class TestRetractedResourcesAreNeverClinicalFacts:
    def test_no_retracted_id_appears_in_any_clinical_section(
        self, snapshot: dict[str, Any]
    ) -> None:
        """Scoped to `data`, which is everything a clinician reads as fact.

        Retracted ids DO appear under `issues` -- that is the reporting
        requirement, not a leak. The next test asserts they must.
        """
        clinical = json.dumps(snapshot["data"])
        for resource_id in RETRACTED_IDS:
            assert resource_id not in clinical, (
                f"{resource_id} is entered-in-error but appears in a clinical section"
            )

    def test_every_retraction_is_reported_in_the_issue_log(
        self, snapshot: dict[str, Any]
    ) -> None:
        """Suppressing silently is its own failure: a snapshot that quietly drops
        a corrected result looks identical to one where it was never taken."""
        reported = {
            issue["resourceId"]
            for issue in snapshot["issues"]
            if issue["code"] == "RESOURCE_ENTERED_IN_ERROR"
        }
        assert reported == RETRACTED_IDS

    def test_all_retracted_resources_are_present_in_the_excluded_collection(
        self, excluded: dict[str, Any]
    ) -> None:
        """Excluded is not deleted. The reader must be able to see that a
        retraction happened."""
        listed = {item["id"] for item in excluded["data"]["excluded"]}
        assert listed == RETRACTED_IDS

    def test_each_exclusion_names_the_field_that_caused_it(
        self, excluded: dict[str, Any]
    ) -> None:
        by_id = {i["id"]: i for i in excluded["data"]["excluded"]}
        assert by_id["condition-002"]["suppressionField"] == "Condition.verificationStatus"
        assert by_id["allergyintolerance-002"]["suppressionField"] == (
            "AllergyIntolerance.verificationStatus"
        )
        assert by_id["observation-004"]["suppressionField"] == "Observation.status"
        assert by_id["encounter-002"]["suppressionField"] == "Encounter.status"

    def test_retracted_critical_lab_value_never_appears_anywhere(
        self, snapshot: dict[str, Any], excluded: dict[str, Any]
    ) -> None:
        """A deliberately literal regression test.

        observation-004 is a retracted creatinine of 14.7 mg/dL -- roughly ten
        times normal. Read on its own it implies renal failure in a patient on
        an ACE inhibitor. It must not be reachable from any endpoint.
        """
        for payload in (snapshot, excluded):
            for path, value in walk(payload):
                assert value != RETRACTED_CREATININE_VALUE, f"retracted value at {path}"
            assert "14.7" not in json.dumps(payload)

    def test_a_fully_retracted_bundle_yields_an_empty_but_valid_snapshot(self) -> None:
        response = client_for(FIXTURES / "all_retracted.json").get(
            "/api/v1/patients/patient-001/snapshot"
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["conditionsCurrent"] == []
        assert data["medicationsActive"] == []
        assert data["allergiesCurrent"] == []
        assert data["vitalSigns"] == []
        assert data["encounters"] == []


# ---------------------------------------------------------------------------
# 2. Terminology displays are never invented
# ---------------------------------------------------------------------------


class TestDisplaysAreNeverInvented:
    def test_every_display_is_traceable_to_the_source_or_the_curated_map(
        self, snapshot: dict[str, Any], raw_bundle_text: str
    ) -> None:
        curated = yaml.safe_load(
            (
                Path(__file__).resolve().parents[2]
                / "src/clinical_snapshot/terminology/displays.yaml"
            ).read_text()
        )
        curated_labels = {
            label
            for system in curated["systems"].values()
            for label in system.get("codes", {}).values()
        }

        for coding in codings(snapshot):
            display, status = coding.get("display"), coding["displayStatus"]
            if status == "unresolved":
                assert display is None, f"unresolved coding carries a display: {coding}"
            elif status in ("from-source", "from-source-unvalidated"):
                assert display is not None and display in raw_bundle_text, (
                    f"display '{display}' claims to come from the source but is not in it"
                )
            elif status == "resolved-local":
                assert display in curated_labels, f"'{display}' is not in the curated map"
                assert coding["displaySource"], "a curated display must cite its source"
            else:
                pytest.fail(f"unknown displayStatus '{status}'")

    def test_the_four_undisplayed_clinical_codes_stay_undisplayed(
        self, snapshot: dict[str, Any]
    ) -> None:
        """E11.9, 4548-4, 849574 and 91936005 have no display in the source.
        We know what several of them mean. The application must not say so."""
        by_code = {c["code"]: c for c in codings(snapshot) if c.get("code")}
        for code in ("E11.9", "849574", "91936005"):
            assert by_code[code]["display"] is None, f"{code} acquired a display"
            assert by_code[code]["displayStatus"] == "unresolved"

    def test_a_system_name_is_offered_even_when_the_display_is_not(
        self, snapshot: dict[str, Any]
    ) -> None:
        """The UI must be able to say 'ICD-10-CM E11.9' rather than a bare URL."""
        by_code = {c["code"]: c for c in codings(snapshot) if c.get("code")}
        assert by_code["E11.9"]["systemName"] == "ICD-10-CM"
        assert by_code["849574"]["systemName"] == "RxNorm"


# ---------------------------------------------------------------------------
# 3. Malformed codes are quarantined from logic
# ---------------------------------------------------------------------------


class TestMalformedCodesAreQuarantined:
    def test_a_code_that_does_not_match_its_system_cannot_drive_logic(
        self, snapshot: dict[str, Any]
    ) -> None:
        for coding in codings(snapshot):
            if coding.get("codeSystemMismatch"):
                assert coding["usableForCodedLogic"] is False
                assert coding["mismatchReason"]

    def test_the_snomed_declared_loinc_shaped_allergy_code_is_flagged(
        self, snapshot: dict[str, Any]
    ) -> None:
        allergy = next(
            a for a in snapshot["data"]["allergiesCurrent"] if a["id"] == "allergyintolerance-001"
        )
        assert allergy["code"]["codeSystemMismatch"] is True
        assert allergy["code"]["usableForCodedLogic"] is False
        # The label is kept: discarding a high-criticality allergy's name is its
        # own harm. It is marked unvalidated instead.
        assert allergy["code"]["display"] == "Penicillin"
        assert allergy["code"]["displayStatus"] == "from-source-unvalidated"

    def test_allergies_are_not_deduplicated(self, snapshot: dict[str, Any]) -> None:
        """De-duplication requires trusting codes, and one of these two does not
        validate. Collapsing them could merge a confirmed high-criticality
        allergy into an unconfirmed one."""
        ids = {a["id"] for a in snapshot["data"]["allergiesCurrent"]}
        assert ids == {"allergyintolerance-001", "allergyintolerance-003"}


# ---------------------------------------------------------------------------
# 4. Date precision is never inflated
# ---------------------------------------------------------------------------


class TestDatePrecisionIsNeverInflated:
    def test_every_rendered_date_appears_verbatim_in_the_source(
        self, snapshot: dict[str, Any], raw_bundle_text: str
    ) -> None:
        """The strongest form of the rule: if a date string reaches the client,
        that exact string was in the bundle."""
        for date in dates(snapshot):
            assert f'"{date["value"]}"' in raw_bundle_text, (
                f"rendered date '{date['value']}' does not appear in the source bundle"
            )

    def test_no_rendered_date_is_longer_than_its_source(
        self, snapshot: dict[str, Any], raw_bundle: dict[str, Any]
    ) -> None:
        source_dates = {v for _, v in walk(raw_bundle) if isinstance(v, str)}
        for date in dates(snapshot):
            assert date["value"] in source_dates

    def test_year_only_values_keep_year_precision(self, snapshot: dict[str, Any]) -> None:
        by_value = {d["value"]: d["precision"] for d in dates(snapshot)}
        assert by_value.get("2019") == "year"
        assert by_value.get("2022") == "year"

    def test_month_precision_survives_a_bundle_that_uses_it(self) -> None:
        payload = (
            client_for(FIXTURES / "month_precision.json")
            .get("/api/v1/patients/patient-001/snapshot")
            .json()
        )
        by_value = {d["value"]: d["precision"] for d in dates(payload)}
        assert by_value.get("2019-07") == "month"


# ---------------------------------------------------------------------------
# 5. Patient scope is never crossed without attribution
# ---------------------------------------------------------------------------


class TestPatientScopeIsolation:
    def test_cross_record_data_is_always_attributed(self, snapshot: dict[str, Any]) -> None:
        """medicationrequest-003 belongs to patient-002. It may appear -- hiding
        an active medication is also a safety failure -- but only under an
        explicit attribution naming the record it came from."""
        medication = next(
            m
            for m in snapshot["data"]["medicationsActive"]
            if m["id"] == "medicationrequest-003"
        )
        assert medication["attribution"] is not None
        assert medication["attribution"]["patientId"] == "patient-002"
        assert "NOT confirmed" in medication["attribution"]["note"]

    def test_the_subjects_own_medications_carry_no_attribution(
        self, snapshot: dict[str, Any]
    ) -> None:
        own = next(
            m
            for m in snapshot["data"]["medicationsActive"]
            if m["id"] == "medicationrequest-001"
        )
        assert own["attribution"] is None

    def test_every_unattributed_clinical_item_belongs_to_the_subject(
        self, snapshot: dict[str, Any], raw_bundle: dict[str, Any]
    ) -> None:
        owner = {}
        for entry in raw_bundle["entry"]:
            resource = entry["resource"]
            ref = (resource.get("subject") or resource.get("patient") or {}).get("reference")
            if ref:
                owner[resource["id"]] = ref.split("/")[-1]

        data = snapshot["data"]
        sections = [
            *data["conditionsCurrent"], *data["conditionsHistorical"],
            *data["medicationsActive"], *data["medicationsHistorical"],
            *data["allergiesCurrent"], *data["allergiesHistorical"],
            *data["vitalSigns"], *data["otherObservations"], *data["encounters"],
        ]
        for item in sections:
            if item.get("attribution"):
                continue
            assert owner.get(item["id"]) == "patient-001", (
                f"{item['id']} belongs to {owner.get(item['id'])} but is unattributed "
                f"in patient-001's snapshot"
            )

    def test_the_other_patients_snapshot_does_not_absorb_the_subjects_data(self) -> None:
        from tests.conftest import BUNDLE_PATH

        payload = (
            client_for(BUNDLE_PATH).get("/api/v1/patients/patient-002/snapshot").json()
        )
        own = [
            m for m in payload["data"]["medicationsActive"] if m["attribution"] is None
        ]
        assert {m["id"] for m in own} == {"medicationrequest-003"}


# ---------------------------------------------------------------------------
# 6. No merge without a source assertion
# ---------------------------------------------------------------------------


class TestNoMergeWithoutSourceAssertion:
    def test_the_supplied_bundle_produces_an_unreconciled_candidate(
        self, snapshot: dict[str, Any]
    ) -> None:
        candidate = snapshot["data"]["identity"]["candidates"][0]
        assert candidate["mergePerformed"] is False
        assert candidate["determination"] == "unreconciled"
        assert candidate["sourceAssertedLink"] is None

    def test_evidence_is_reported_on_both_sides(self, snapshot: dict[str, Any]) -> None:
        candidate = snapshot["data"]["identity"]["candidates"][0]
        assert len(candidate["evidenceFor"]) >= 3
        assert len(candidate["evidenceAgainst"]) >= 3

    def test_the_user_is_warned_prominently(self, snapshot: dict[str, Any]) -> None:
        codes = {w["code"] for w in snapshot["data"]["warnings"]}
        assert "DUPLICATE_CANDIDATE_UNRECONCILED" in codes
        warning = next(
            w
            for w in snapshot["data"]["warnings"]
            if w["code"] == "DUPLICATE_CANDIDATE_UNRECONCILED"
        )
        assert warning["severity"] == "high"
        assert "NOT been merged" in warning["message"]
        assert "active medication" in warning["message"]

    def test_a_source_asserted_link_authorises_reconciliation(self) -> None:
        payload = (
            client_for(FIXTURES / "linked_patients.json")
            .get("/api/v1/patients/patient-001/snapshot")
            .json()
        )
        candidate = payload["data"]["identity"]["candidates"][0]
        assert candidate["determination"] == "source-asserted-link"
        assert candidate["mergePerformed"] is True
        assert candidate["sourceAssertedLink"] == "replaces"


# ---------------------------------------------------------------------------
# 7. Conservation: nothing is silently dropped
# ---------------------------------------------------------------------------


class TestConservation:
    def test_every_bundle_entry_is_accounted_for(
        self, snapshot: dict[str, Any], excluded: dict[str, Any], raw_bundle: dict[str, Any]
    ) -> None:
        """Across both patients' snapshots plus the excluded collection, every
        non-Patient entry in the bundle must appear exactly once."""
        from tests.conftest import BUNDLE_PATH

        expected = {
            e["resource"]["id"]
            for e in raw_bundle["entry"]
            if e["resource"]["resourceType"] != "Patient"
        }

        seen: set[str] = set()
        for patient_id in ("patient-001", "patient-002"):
            payload = (
                client_for(BUNDLE_PATH).get(f"/api/v1/patients/{patient_id}/snapshot").json()
            )
            data = payload["data"]
            for key in (
                "conditionsCurrent", "conditionsHistorical", "medicationsActive",
                "medicationsHistorical", "allergiesCurrent", "allergiesHistorical",
                "vitalSigns", "otherObservations", "encounters", "needsReview",
            ):
                seen.update(item["id"] for item in data[key])
            drawer = (
                client_for(BUNDLE_PATH).get(f"/api/v1/patients/{patient_id}/excluded").json()
            )
            seen.update(item["id"] for item in drawer["data"]["excluded"])

        assert expected - seen == set(), f"resources vanished: {expected - seen}"

    def test_unrenderable_observation_is_surfaced_not_dropped(
        self, snapshot: dict[str, Any]
    ) -> None:
        review = {item["id"] for item in snapshot["data"]["needsReview"]}
        assert "observation-002" in review


# ---------------------------------------------------------------------------
# 8. Unknowns are reported, not hidden
# ---------------------------------------------------------------------------


class TestUnknownsAreReported:
    def test_unresolved_references_are_rendered_as_unresolved(
        self, snapshot: dict[str, Any]
    ) -> None:
        """'This condition has no encounter' and 'this condition's encounter is
        missing from the bundle' must not look the same."""
        condition = next(
            c for c in snapshot["data"]["conditionsCurrent"] if c["id"] == "condition-003"
        )
        assert condition["encounter"]["resolved"] is False
        assert condition["encounter"]["reason"] == "REFERENCE_TARGET_NOT_IN_BUNDLE"
        assert condition["encounter"]["reference"] == "Encounter/encounter-099"

    def test_every_unresolved_reference_has_a_matching_issue(
        self, snapshot: dict[str, Any]
    ) -> None:
        rendered = {
            ref["reference"]
            for ref in objects(snapshot["data"], lambda d: d.get("resolved") is False)
        }
        reported = {
            issue["detail"].get("target")
            for issue in snapshot["issues"]
            if issue["code"] == "REFERENCE_UNRESOLVED"
        }
        assert rendered <= reported

    def test_no_abnormal_flag_is_derived_without_a_reference_range(
        self, snapshot: dict[str, Any]
    ) -> None:
        for observation in snapshot["data"]["vitalSigns"] + snapshot["data"]["otherObservations"]:
            assert observation["referenceRangeAvailable"] is False
            assert observation["interpretationAvailable"] is False

    def test_missing_us_core_must_support_elements_are_reported(
        self, snapshot: dict[str, Any]
    ) -> None:
        """patient-001 claims the US Core profile but has no birthsex extension."""
        assert snapshot["data"]["patient"]["usCore"]["birthsex"] is None
        codes = {i["code"] for i in snapshot["issues"]}
        assert "USCORE_ELEMENT_MISSING" in codes

    def test_condition_category_absence_is_declared_to_the_ui(
        self, snapshot: dict[str, Any]
    ) -> None:
        """Without Condition.category we cannot call this a problem list."""
        assert snapshot["data"]["conditionsCategoryDeclared"] is False
        for condition in snapshot["data"]["conditionsCurrent"]:
            assert condition["categoryDeclared"] is False


# ---------------------------------------------------------------------------
# 9. Degenerate input
# ---------------------------------------------------------------------------


class TestDegenerateInput:
    def test_an_empty_bundle_does_not_crash_the_api(self) -> None:
        client = client_for(FIXTURES / "empty_bundle.json")
        assert client.get("/health").status_code == 200
        assert client.get("/api/v1/patients").json()["data"]["patients"] == []
        assert client.get("/api/v1/patients/patient-001/snapshot").status_code == 404
