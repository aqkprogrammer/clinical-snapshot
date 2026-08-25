from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
BUNDLE_PATH = REPO_ROOT / "data" / "scenario1_fhir_bundle.json"
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def bundle_path() -> Path:
    return BUNDLE_PATH


@pytest.fixture(scope="session")
def raw_bundle_text() -> str:
    return BUNDLE_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def raw_bundle() -> dict[str, Any]:
    return json.loads(BUNDLE_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def client(bundle_path: Path):  # type: ignore[no-untyped-def]
    from fastapi.testclient import TestClient

    from clinical_snapshot.config import Settings, get_settings
    from clinical_snapshot.main import app

    app.dependency_overrides[get_settings] = lambda: Settings(bundle_path=bundle_path)
    yield TestClient(app)
    app.dependency_overrides.clear()


def client_for(path: Path):  # type: ignore[no-untyped-def]
    """A TestClient bound to an arbitrary bundle, for adversarial fixtures."""
    from fastapi.testclient import TestClient

    from clinical_snapshot.config import Settings, get_settings
    from clinical_snapshot.main import app

    app.dependency_overrides[get_settings] = lambda: Settings(bundle_path=path)
    return TestClient(app)


def walk(node: Any, path: str = "") -> Any:
    """Yield (path, value) for every scalar in a JSON document."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield from walk(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from walk(value, f"{path}[{index}]")
    else:
        yield path, node


def objects(node: Any, predicate) -> Any:  # type: ignore[no-untyped-def]
    """Yield every dict in a JSON document matching a predicate."""
    if isinstance(node, dict):
        if predicate(node):
            yield node
        for value in node.values():
            yield from objects(value, predicate)
    elif isinstance(node, list):
        for value in node:
            yield from objects(value, predicate)
