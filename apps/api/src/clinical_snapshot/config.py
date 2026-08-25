"""Runtime configuration."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CLINICAL_SNAPSHOT_", env_file=".env", extra="ignore"
    )

    bundle_path: Path = _REPO_ROOT / "data" / "scenario1_fhir_bundle.json"
    """Which bundle to serve. The data directory is scanned for siblings, so
    additional scenarios can be dropped in without a code change."""

    withhold_excluded_observation_values: bool = True
    """Whether the numeric value of a retracted Observation is withheld from the
    excluded collection.

    Defaults to True. The bundle's retracted result is a creatinine of
    14.7 mg/dL -- roughly ten times normal, and read on its own it implies
    renal failure in a patient on an ACE inhibitor. Showing the number even
    inside a drawer labelled "retracted" risks it being read and acted on. The
    resource, its code, and the fact of the retraction are always shown.
    """

    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]


def get_settings() -> Settings:
    return Settings()
