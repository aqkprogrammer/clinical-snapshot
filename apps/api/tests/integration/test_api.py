"""API contract: shapes, status codes, and error format."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient


class TestHealth:
    def test_unversioned_alias_still_answers(self, client: TestClient) -> None:
        assert client.get("/health").json()["status"] == "ok"

    def test_reports_the_loaded_bundle(self, client: TestClient) -> None:
        body = client.get("/api/v1/health").json()
        assert body["status"] == "ok"
        assert body["bundleLoaded"] is True
        assert body["bundleId"] == "scenario1-synthetic-bundle"
        assert body["patientCount"] == 2


class TestPatients:
    def test_lists_every_patient_record_without_merging_them(
        self, client: TestClient
    ) -> None:
        data = client.get("/api/v1/patients").json()["data"]
        assert {p["id"] for p in data["patients"]} == {"patient-001", "patient-002"}

    def test_reports_resource_counts_per_record(self, client: TestClient) -> None:
        data = client.get("/api/v1/patients").json()["data"]
        by_id = {p["id"]: p for p in data["patients"]}
        assert by_id["patient-002"]["resourceCounts"] == {"MedicationRequest": 1}

    def test_exposes_the_duplicate_candidate_with_evidence(self, client: TestClient) -> None:
        candidates = client.get("/api/v1/patients").json()["data"]["duplicateCandidates"]
        assert len(candidates) == 1
        assert candidates[0]["recommendedAction"].startswith("human-steward-review")
        assert candidates[0]["confidence"] == "conflicted"

    def test_preserves_birthdate_precision_in_the_listing(self, client: TestClient) -> None:
        by_id = {
            p["id"]: p for p in client.get("/api/v1/patients").json()["data"]["patients"]
        }
        assert by_id["patient-001"]["birthDate"] == {
            "value": "1958-03-12",
            "precision": "day",
        }
        assert by_id["patient-002"]["birthDate"] == {"value": "1958", "precision": "year"}


class TestSnapshot:
    def test_returns_the_documented_envelope(self, client: TestClient) -> None:
        body = client.get("/api/v1/patients/patient-001/snapshot").json()
        assert set(body) == {"meta", "data", "issues"}
        assert body["meta"]["patientId"] == "patient-001"
        assert "No Patient records were merged" in body["meta"]["scopeNote"]

    def test_separates_active_from_historical_medications(self, client: TestClient) -> None:
        data = client.get("/api/v1/patients/patient-001/snapshot").json()["data"]
        assert {m["id"] for m in data["medicationsHistorical"]} == {"medicationrequest-002"}
        assert "medicationrequest-002" not in {m["id"] for m in data["medicationsActive"]}

    def test_reports_staleness(self, client: TestClient) -> None:
        meta = client.get("/api/v1/patients/patient-001/snapshot").json()["meta"]
        assert meta["daysSinceLatestActivity"] > 180
        assert meta["latestClinicalActivity"] == "2025-11-04T15:00:00Z"

    def test_surfaces_us_core_extensions_that_are_present(self, client: TestClient) -> None:
        patient = client.get("/api/v1/patients/patient-001/snapshot").json()["data"]["patient"]
        assert patient["usCore"]["race"]["display"] == "White"
        assert patient["usCore"]["ethnicity"]["display"] == "Not Hispanic or Latino"
        assert patient["profilesClaimed"] == [
            "http://hl7.org/fhir/us/core/StructureDefinition/us-core-patient"
        ]

    def test_ssn_is_never_exposed(self, client: TestClient) -> None:
        """A clinical snapshot has no use for a national identifier, so it is
        withheld entirely rather than merely masked."""
        body = client.get("/api/v1/patients/patient-001/snapshot").text
        assert "4471" not in body
        assert "us-ssn" not in body

    def test_withheld_identifiers_are_counted_so_the_omission_is_visible(
        self, client: TestClient
    ) -> None:
        patient = client.get("/api/v1/patients/patient-001/snapshot").json()["data"]["patient"]
        assert patient["withheldIdentifierCount"] == 1
        assert [i["systemName"] for i in patient["identifiers"]] == ["MRN"]

    def test_mrn_is_retained_because_the_duplicate_warning_needs_it(
        self, client: TestClient
    ) -> None:
        patient = client.get("/api/v1/patients/patient-001/snapshot").json()["data"]["patient"]
        assert any(i["value"] == "MRN-48213" for i in patient["identifiers"])


class TestDataQuality:
    def test_returns_a_severity_summary_and_the_full_log(self, client: TestClient) -> None:
        data = client.get("/api/v1/patients/patient-001/data-quality").json()["data"]
        assert set(data["summary"]) == {"high", "medium", "low"}
        assert data["summary"]["high"] >= 5
        assert len(data["issues"]) == sum(data["summary"].values())

    def test_issues_are_ranked_most_severe_first(self, client: TestClient) -> None:
        issues = client.get("/api/v1/patients/patient-001/data-quality").json()["data"]["issues"]
        rank = {"high": 0, "medium": 1, "low": 2}
        severities = [rank[i["severity"]] for i in issues]
        assert severities == sorted(severities)

    def test_detects_the_bundle_level_structural_defects(self, client: TestClient) -> None:
        codes = {
            i["code"]
            for i in client.get("/api/v1/patients/patient-001/data-quality").json()["data"][
                "issues"
            ]
        }
        assert {
            "BDL_TOTAL_ON_COLLECTION",
            "BDL_INVALID_UUID",
            "BDL_REFERENCE_SCHEME_MISMATCH",
            "BDL_NO_PROVENANCE",
        } <= codes


class TestErrors:
    def test_unknown_patient_returns_problem_json(self, client: TestClient) -> None:
        response = client.get("/api/v1/patients/does-not-exist/snapshot")
        assert response.status_code == 404
        assert response.headers["content-type"].startswith("application/problem+json")
        body: dict[str, Any] = response.json()
        assert set(body) >= {"type", "title", "status", "instance"}
        assert body["status"] == 404

    def test_openapi_schema_is_served(self, client: TestClient) -> None:
        assert client.get("/openapi.json").status_code == 200
