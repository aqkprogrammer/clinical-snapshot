"""Typed data-quality issues.

Every stage of the pipeline reports what it could not do cleanly. Nothing is
silently dropped, coerced, or invented: if a decision was made about imperfect
input, there is an issue here recording it.

The issue log is part of the API payload, not a server-side log file. A
clinician-facing snapshot that quietly discards a retracted lab result is
indistinguishable from one that never had it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Severity(StrEnum):
    """How much this issue should worry a reader of the snapshot."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class IssueCode(StrEnum):
    """Stable identifiers for every class of problem we detect.

    Stable because they are part of the API contract and are asserted against
    by the safety test suite.
    """

    # --- Bundle-level structure -------------------------------------------
    BDL_TOTAL_ON_COLLECTION = "BDL_TOTAL_ON_COLLECTION"
    BDL_ENTRY_COUNT_MISMATCH = "BDL_ENTRY_COUNT_MISMATCH"
    BDL_INVALID_UUID = "BDL_INVALID_UUID"
    BDL_DUPLICATE_FULLURL = "BDL_DUPLICATE_FULLURL"
    BDL_DUPLICATE_RESOURCE_ID = "BDL_DUPLICATE_RESOURCE_ID"
    BDL_REFERENCE_SCHEME_MISMATCH = "BDL_REFERENCE_SCHEME_MISMATCH"
    BDL_NO_PROVENANCE = "BDL_NO_PROVENANCE"

    # --- Parsing ----------------------------------------------------------
    RESOURCE_UNPARSEABLE = "RESOURCE_UNPARSEABLE"
    RESOURCE_TYPE_UNSUPPORTED = "RESOURCE_TYPE_UNSUPPORTED"
    RESOURCE_ID_MISSING = "RESOURCE_ID_MISSING"

    # --- References -------------------------------------------------------
    REFERENCE_UNRESOLVED = "REFERENCE_UNRESOLVED"
    REFERENCE_MALFORMED = "REFERENCE_MALFORMED"
    REFERENCE_TYPE_MISMATCH = "REFERENCE_TYPE_MISMATCH"

    # --- Terminology ------------------------------------------------------
    TERMINOLOGY_DISPLAY_MISSING = "TERMINOLOGY_DISPLAY_MISSING"
    CODE_SYSTEM_MISMATCH = "CODE_SYSTEM_MISMATCH"

    # --- Temporal ---------------------------------------------------------
    DATE_PRECISION_REDUCED = "DATE_PRECISION_REDUCED"
    SNAPSHOT_STALE = "SNAPSHOT_STALE"

    # --- Profile / completeness -------------------------------------------
    USCORE_ELEMENT_MISSING = "USCORE_ELEMENT_MISSING"
    OBSERVATION_CATEGORY_ABSENT = "OBSERVATION_CATEGORY_ABSENT"
    CONDITION_CATEGORY_ABSENT = "CONDITION_CATEGORY_ABSENT"
    REFERENCE_RANGE_ABSENT = "REFERENCE_RANGE_ABSENT"

    # --- Safety / identity ------------------------------------------------
    RESOURCE_ENTERED_IN_ERROR = "RESOURCE_ENTERED_IN_ERROR"
    RESOURCE_NEEDS_REVIEW = "RESOURCE_NEEDS_REVIEW"
    DUPLICATE_CANDIDATE_UNRECONCILED = "DUPLICATE_CANDIDATE_UNRECONCILED"
    CROSS_RECORD_CLINICAL_DATA = "CROSS_RECORD_CLINICAL_DATA"


@dataclass(frozen=True, slots=True)
class DataQualityIssue:
    """One thing that was wrong, ambiguous, or unresolvable in the source."""

    code: IssueCode
    severity: Severity
    message: str
    resource_id: str | None = None
    resource_type: str | None = None
    path: str | None = None
    detail: dict[str, str] = field(default_factory=dict)


_SEVERITY_ORDER = {Severity.HIGH: 0, Severity.MEDIUM: 1, Severity.LOW: 2}


class IssueLog:
    """Append-only collector, shared across pipeline stages."""

    def __init__(self) -> None:
        self._issues: list[DataQualityIssue] = []

    def add(
        self,
        code: IssueCode,
        severity: Severity,
        message: str,
        *,
        resource_id: str | None = None,
        resource_type: str | None = None,
        path: str | None = None,
        detail: dict[str, str] | None = None,
    ) -> None:
        self._issues.append(
            DataQualityIssue(
                code=code,
                severity=severity,
                message=message,
                resource_id=resource_id,
                resource_type=resource_type,
                path=path,
                detail=dict(detail or {}),
            )
        )

    def all(self) -> list[DataQualityIssue]:
        """Issues ranked by severity, then by code, for stable presentation."""
        return sorted(
            self._issues,
            key=lambda i: (_SEVERITY_ORDER[i.severity], i.code, i.resource_id or ""),
        )

    def with_code(self, code: IssueCode) -> list[DataQualityIssue]:
        return [i for i in self._issues if i.code == code]

    def summary(self) -> dict[str, int]:
        counts = {s.value: 0 for s in Severity}
        for issue in self._issues:
            counts[issue.severity.value] += 1
        return counts

    def __len__(self) -> int:
        return len(self._issues)
