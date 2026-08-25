"""The API must not crash on bad input -- neither a bad bundle nor a bad path.

The brief is explicit that a missing or malformed reference must not take the
API down. These tests extend that to the two remaining sources of bad input:
the bundle file itself, and the path parameter.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from clinical_snapshot.config import Settings, get_settings
from clinical_snapshot.main import app

CLINICAL_ENDPOINTS = [
    "/api/v1/patients",
    "/api/v1/patients/patient-001/snapshot",
    "/api/v1/patients/patient-001/excluded",
    "/api/v1/patients/patient-001/data-quality",
]


def client_for(path: Path) -> Iterator[TestClient]:
    app.dependency_overrides[get_settings] = lambda: Settings(bundle_path=path)
    # raise_server_exceptions=False so an unhandled error surfaces as the
    # response a real client would receive, rather than propagating.
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


@pytest.fixture
def broken_json(tmp_path: Path) -> Iterator[TestClient]:
    path = tmp_path / "broken.json"
    path.write_text('{"resourceType": "Bundle", "entry": [ BROKEN', encoding="utf-8")
    yield from client_for(path)


@pytest.fixture
def wrong_shape(tmp_path: Path) -> Iterator[TestClient]:
    path = tmp_path / "wrong.json"
    path.write_text(json.dumps({"resourceType": "Bundle", "entry": "not-a-list"}), encoding="utf-8")
    yield from client_for(path)


@pytest.fixture
def absent(tmp_path: Path) -> Iterator[TestClient]:
    yield from client_for(tmp_path / "nope.json")


class TestMalformedBundle:
    @pytest.mark.parametrize("endpoint", CLINICAL_ENDPOINTS)
    def test_unparseable_json_yields_503_problem_json(
        self, broken_json: TestClient, endpoint: str
    ) -> None:
        response = broken_json.get(endpoint)
        assert response.status_code == 503
        assert response.headers["content-type"].startswith("application/problem+json")

    @pytest.mark.parametrize("endpoint", CLINICAL_ENDPOINTS)
    def test_wrong_shaped_bundle_yields_503_problem_json(
        self, wrong_shape: TestClient, endpoint: str
    ) -> None:
        assert wrong_shape.get(endpoint).status_code == 503

    @pytest.mark.parametrize("endpoint", CLINICAL_ENDPOINTS)
    def test_absent_bundle_yields_503_problem_json(
        self, absent: TestClient, endpoint: str
    ) -> None:
        assert absent.get(endpoint).status_code == 503

    def test_no_endpoint_ever_returns_a_plain_text_500(
        self, broken_json: TestClient, wrong_shape: TestClient
    ) -> None:
        for client in (broken_json, wrong_shape):
            for endpoint in [*CLINICAL_ENDPOINTS, "/api/v1/health", "/health"]:
                response = client.get(endpoint)
                assert response.status_code != 500
                assert "text/plain" not in response.headers.get("content-type", "")

    def test_the_error_body_does_not_disclose_the_bundle_path(
        self, broken_json: TestClient, tmp_path: Path
    ) -> None:
        """A 503 tells the caller the service is misconfigured, not where."""
        body = broken_json.get("/api/v1/patients").text
        assert str(tmp_path) not in body
        assert "broken.json" not in body

    def test_the_problem_document_has_the_documented_shape(
        self, broken_json: TestClient
    ) -> None:
        body = broken_json.get("/api/v1/patients").json()
        assert set(body) >= {"type", "title", "status", "instance"}
        assert body["status"] == 503


class TestHealthDegradesRatherThanFailing:
    def test_unparseable_bundle_reports_degraded(self, broken_json: TestClient) -> None:
        body = broken_json.get("/api/v1/health").json()
        assert body["status"] == "degraded"
        assert body["bundleLoaded"] is False
        assert body["patientCount"] == 0

    def test_wrong_shaped_bundle_reports_degraded(self, wrong_shape: TestClient) -> None:
        assert wrong_shape.get("/api/v1/health").json()["status"] == "degraded"

    def test_absent_bundle_reports_degraded(self, absent: TestClient) -> None:
        assert absent.get("/api/v1/health").json()["status"] == "degraded"

    def test_health_stays_200_because_it_is_a_liveness_probe(
        self, broken_json: TestClient
    ) -> None:
        """Failing the probe would stop the stack coming up at all, instead of
        letting it come up and report what is wrong. Readiness should key on
        bundleLoaded."""
        assert broken_json.get("/api/v1/health").status_code == 200
        assert broken_json.get("/health").status_code == 200

    def test_health_does_not_disclose_the_path(self, broken_json: TestClient) -> None:
        assert "broken.json" not in broken_json.get("/api/v1/health").text


class TestPathParameterValidation:
    @pytest.mark.parametrize(
        "patient_id",
        [
            "patient-001' OR 1=1",
            "<script>x",          # a slash would not match the route at all
            "a" * 65,
            "patient 001",
            "patient$001",
            "patient%09id",       # tab, percent-encoded so it reaches the server
            "%00",
        ],
    )
    def test_ids_outside_the_fhir_charset_are_rejected_before_any_handler(
        self, client: TestClient, patient_id: str
    ) -> None:
        response = client.get(f"/api/v1/patients/{patient_id}/snapshot")
        assert response.status_code == 422
        assert response.headers["content-type"].startswith("application/problem+json")

    def test_the_rejected_value_is_not_echoed_back(self, client: TestClient) -> None:
        """422 names the field that failed, not the value that failed it."""
        response = client.get("/api/v1/patients/%3Cscript%3Ex/snapshot")
        assert response.status_code == 422
        assert "script" not in response.json()["title"]
        assert all("script" not in error["message"] for error in response.json()["errors"])

    def test_validation_errors_use_the_same_problem_shape(self, client: TestClient) -> None:
        body = client.get("/api/v1/patients/bad id/snapshot").json()
        assert set(body) >= {"type", "title", "status", "instance", "errors"}
        assert body["status"] == 422
        assert body["errors"][0]["location"].endswith("patient_id")

    @pytest.mark.parametrize(
        "endpoint", ["snapshot", "excluded", "data-quality"]
    )
    def test_validation_applies_to_every_patient_endpoint(
        self, client: TestClient, endpoint: str
    ) -> None:
        assert client.get(f"/api/v1/patients/bad id/{endpoint}").status_code == 422

    def test_a_well_formed_but_unknown_id_is_still_a_404(self, client: TestClient) -> None:
        """Validation must not swallow the genuine not-found case."""
        response = client.get("/api/v1/patients/patient-999/snapshot")
        assert response.status_code == 404
        assert "patient-999" in response.json()["title"]

    def test_valid_ids_are_unaffected(self, client: TestClient) -> None:
        for endpoint in ("snapshot", "excluded", "data-quality"):
            assert client.get(f"/api/v1/patients/patient-001/{endpoint}").status_code == 200

    def test_dots_and_hyphens_are_accepted_as_fhir_permits(self, client: TestClient) -> None:
        """A valid-but-absent id reaches the 404 path rather than being rejected."""
        assert client.get("/api/v1/patients/a.b-c/snapshot").status_code == 404

    @pytest.mark.parametrize(
        "attempt",
        ["patient%2F..%2Fadmin", "..%2F..%2Fetc%2Fpasswd", "patient-001%2Fextra"],
    )
    def test_encoded_path_traversal_never_reaches_a_handler(
        self, client: TestClient, attempt: str
    ) -> None:
        """Percent-encoded separators decode before routing, so these fail to
        match rather than being validated -- either way, never a 200."""
        response = client.get(f"/api/v1/patients/{attempt}/snapshot")
        assert response.status_code in (404, 422)
        assert response.headers["content-type"].startswith("application/problem+json")
