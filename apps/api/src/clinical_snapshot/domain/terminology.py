"""Display resolution, and the refusal to invent one.

A code with no display is a hole in the data. There are two ways to fill it:
look it up somewhere auditable, or recall what it probably means. Only the
first is acceptable here, and our auditable source is deliberately narrow --
see `terminology/displays.yaml` for the scope rule.

This module also performs a structural check of code *format* against the
declared system. The bundle contains an AllergyIntolerance whose system is
SNOMED CT but whose code is `7980-2`: hyphenated, LOINC-shaped, and not a
well-formed SNOMED concept identifier. The accompanying display says
"Penicillin". We keep the display -- discarding the label of a high-criticality
allergy is its own harm -- but we mark it unvalidated and bar the code from any
coded logic, because we cannot tell which of the two fields is wrong.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from importlib.resources import files
from typing import Any

import yaml

from .issues import IssueCode, IssueLog, Severity

SNOMED = "http://snomed.info/sct"
LOINC = "http://loinc.org"
RXNORM = "http://www.nlm.nih.gov/research/umls/rxnorm"
ICD10CM = "http://hl7.org/fhir/sid/icd-10-cm"

# Structural shapes only. These say nothing about whether a code *exists* --
# that needs a terminology server -- only whether it could possibly belong to
# the system it claims.
_CODE_SHAPES: dict[str, tuple[re.Pattern[str], str]] = {
    SNOMED: (re.compile(r"^[1-9]\d{5,17}$"), "6-18 digits with no separators"),
    LOINC: (re.compile(r"^\d{1,5}-\d$"), "digits followed by a hyphen and a check digit"),
    RXNORM: (re.compile(r"^\d+$"), "digits only"),
    ICD10CM: (
        re.compile(r"^[A-TV-Z]\d[0-9A-Z](?:\.[0-9A-Z]{1,4})?$"),
        "a letter followed by 2-6 alphanumerics, optionally dotted",
    ),
}


class DisplayStatus(StrEnum):
    """Where a rendered display came from -- or why there isn't one."""

    FROM_SOURCE = "from-source"
    """The bundle supplied it and the code is well-formed for its system."""

    FROM_SOURCE_UNVALIDATED = "from-source-unvalidated"
    """The bundle supplied it, but the code does not validate against the
    declared system, so the display is unverified free text."""

    RESOLVED_LOCAL = "resolved-local"
    """Filled in from the curated FHIR CodeSystem map."""

    UNRESOLVED = "unresolved"
    """No display available. Renders as "code unavailable", never guessed."""


@dataclass(frozen=True, slots=True)
class ResolvedCoding:
    """A coding prepared for display, with the provenance of its label."""

    system: str | None
    code: str | None
    display: str | None
    display_status: DisplayStatus
    system_name: str | None = None
    display_source: str | None = None
    code_system_mismatch: bool = False
    mismatch_reason: str | None = None
    usable_for_coded_logic: bool = True


@lru_cache(maxsize=1)
def _load_map() -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    raw = yaml.safe_load(
        files("clinical_snapshot.terminology").joinpath("displays.yaml").read_text(encoding="utf-8")
    )
    return raw.get("systems", {}), raw.get("external_systems", {})


class TerminologyService:
    """Resolves displays from the curated map only."""

    def __init__(self, issues: IssueLog) -> None:
        self._issues = issues
        self._systems, self._external = _load_map()

    def system_name(self, system: str | None) -> str | None:
        """A short human label for the system itself, so the UI can say
        'ICD-10-CM E11.9' rather than showing a bare URL."""
        if system is None:
            return None
        entry = self._systems.get(system)
        if entry:
            name: str = entry.get("name", system)
            return name
        return self._external.get(system, system)

    def resolve(
        self,
        system: str | None,
        code: str | None,
        display: str | None,
        *,
        source_id: str | None = None,
        source_type: str | None = None,
        path: str | None = None,
    ) -> ResolvedCoding:
        system_name = self.system_name(system)
        mismatch_reason = self._check_code_shape(system, code)

        if mismatch_reason is not None:
            self._issues.add(
                IssueCode.CODE_SYSTEM_MISMATCH,
                Severity.HIGH,
                f"Code '{code}' is not well-formed for {system_name}: expected "
                f"{mismatch_reason}. "
                + (
                    f"The supplied display '{display}' is therefore unvalidated."
                    if display
                    else "No display was supplied."
                ),
                resource_id=source_id,
                resource_type=source_type,
                path=path,
                detail={"system": str(system), "code": str(code)},
            )
            return ResolvedCoding(
                system=system,
                code=code,
                display=display,
                display_status=(
                    DisplayStatus.FROM_SOURCE_UNVALIDATED if display else DisplayStatus.UNRESOLVED
                ),
                system_name=system_name,
                code_system_mismatch=True,
                mismatch_reason=(
                    f"Code '{code}' is not a well-formed identifier for {system_name} "
                    f"(expected {mismatch_reason})"
                ),
                usable_for_coded_logic=False,
            )

        if display and display.strip():
            return ResolvedCoding(
                system=system,
                code=code,
                display=display.strip(),
                display_status=DisplayStatus.FROM_SOURCE,
                system_name=system_name,
            )

        local = self._lookup_local(system, code)
        if local is not None:
            label, source = local
            return ResolvedCoding(
                system=system,
                code=code,
                display=label,
                display_status=DisplayStatus.RESOLVED_LOCAL,
                system_name=system_name,
                display_source=source,
            )

        self._issues.add(
            IssueCode.TERMINOLOGY_DISPLAY_MISSING,
            Severity.MEDIUM,
            f"No display available for {system_name} code '{code}'. Rendered without a "
            f"human-readable label rather than guessing one.",
            resource_id=source_id,
            resource_type=source_type,
            path=path,
            detail={"system": str(system), "code": str(code)},
        )
        return ResolvedCoding(
            system=system,
            code=code,
            display=None,
            display_status=DisplayStatus.UNRESOLVED,
            system_name=system_name,
        )

    # -- internals ---------------------------------------------------------

    def _lookup_local(self, system: str | None, code: str | None) -> tuple[str, str] | None:
        if system is None or code is None:
            return None
        entry = self._systems.get(system)
        if not entry:
            return None
        label = entry.get("codes", {}).get(code)
        if label is None:
            return None
        return str(label), str(entry.get("source", system))

    @staticmethod
    def _check_code_shape(system: str | None, code: str | None) -> str | None:
        """Returns a description of the expected shape when the code violates
        it, else None. Systems we have no shape rule for always pass."""
        if system is None or code is None:
            return None
        shape = _CODE_SHAPES.get(system)
        if shape is None:
            return None
        pattern, description = shape
        return None if pattern.match(code) else description
