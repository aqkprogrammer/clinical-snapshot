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

from ..fhir.models import CodeableConcept
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


class DisplaySource(StrEnum):
    """Where a display came from. Never "the model knew it".

    Deliberately coarse and auditable: a reader can answer "who said this
    concept is called that?" from this field alone.
    """

    FHIR = "fhir"
    """The bundle supplied the display. We pass it through unchanged."""

    VERIFIED_LOCAL_MAP = "verified-local-map"
    """Filled from the curated map of FHIR-specification CodeSystems. The
    citation is in `display_source_detail`."""

    UNAVAILABLE = "unavailable"
    """No display, and none was inferred. Renders as "display unavailable"."""


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
    display_source: DisplaySource = DisplaySource.UNAVAILABLE
    display_source_detail: str | None = None
    """Citation for a curated display, e.g. the FHIR CodeSystem it came from."""
    code_system_mismatch: bool = False
    mismatch_reason: str | None = None
    usable_for_coded_logic: bool = True


@dataclass(frozen=True, slots=True)
class ResolvedConcept:
    """A CodeableConcept prepared for display.

    FHIR permits several codings as translations of one concept. We render the
    first and retain the rest rather than picking a "best" system -- choosing
    between SNOMED CT and ICD-10 for the same concept is a terminology
    decision we have no basis to make here.
    """

    primary: ResolvedCoding
    alternates: tuple[ResolvedCoding, ...] = ()
    text: str | None = None

    @property
    def has_alternates(self) -> bool:
        return bool(self.alternates)


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
        return self._external.get(system) or self._shorten(system)

    @staticmethod
    def _shorten(system: str) -> str:
        """Display label for a system URI we have no name for.

        Returns the final path segment of the URI. This is a shortening of what
        the source literally said, not an interpretation of it -- an unknown
        system stays unknown, it just stops rendering as a full URL in a
        clinician-facing header. The complete URI remains in the payload.
        """
        tail = system.rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1]
        return tail.upper() if len(tail) <= 5 else tail

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
                display_source=DisplaySource.FHIR if display else DisplaySource.UNAVAILABLE,
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
                display_source=DisplaySource.FHIR,
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
                display_source=DisplaySource.VERIFIED_LOCAL_MAP,
                display_source_detail=source,
            )

        if system is None and code is None:
            return ResolvedCoding(
                system=None,
                code=None,
                display=None,
                display_status=DisplayStatus.UNRESOLVED,
                system_name=None,
                display_source=DisplaySource.UNAVAILABLE,
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
            display_source=DisplaySource.UNAVAILABLE,
        )

    def resolve_concept(
        self,
        concept: CodeableConcept | None,
        *,
        source_id: str | None = None,
        source_type: str | None = None,
        path: str | None = None,
    ) -> ResolvedConcept:
        """Resolve every coding in a CodeableConcept, preserving order.

        With no codings at all, falls back to `CodeableConcept.text` -- which
        is the source's own words, not an inference.
        """
        codings = list(concept.coding) if concept else []
        text = concept.text if concept else None

        if not codings:
            return ResolvedConcept(
                primary=self.resolve(
                    None, None, text, source_id=source_id, source_type=source_type, path=path
                ),
                text=text,
            )

        resolved = [
            self.resolve(
                coding.system,
                coding.code,
                coding.display,
                source_id=source_id,
                source_type=source_type,
                path=f"{path}.coding[{index}]" if path else None,
            )
            for index, coding in enumerate(codings)
        ]
        return ResolvedConcept(primary=resolved[0], alternates=tuple(resolved[1:]), text=text)

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
