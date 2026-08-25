"""Bundle loading, structural validation, and per-resource parsing.

Parsing is lenient by design (see `models.py`) but never silent: a resource
that fails to validate is reported and excluded from the index rather than
crashing the request or vanishing from the entry tally.
"""

from __future__ import annotations

import json
import uuid
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from ..domain.issues import IssueCode, IssueLog, Severity
from .index import ResourceIndex
from .models import RESOURCE_MODELS, Bundle, DomainResource, UnknownResource

_URN_UUID_PREFIX = "urn:uuid:"


@dataclass(slots=True)
class LoadedBundle:
    """A parsed bundle plus everything we learned while parsing it."""

    bundle: Bundle
    index: ResourceIndex
    issues: IssueLog
    unparsed_entry_count: int = 0
    full_urls: list[str] = field(default_factory=list)

    @property
    def entry_count(self) -> int:
        return len(self.bundle.entry)


def load_bundle(path: Path, issues: IssueLog | None = None) -> LoadedBundle:
    """Read, validate, and index a FHIR bundle from disk."""
    issues = issues or IssueLog()
    raw = json.loads(path.read_text(encoding="utf-8"))
    bundle = Bundle.model_validate(raw)

    _check_bundle_structure(bundle, issues)

    index = ResourceIndex()
    unparsed = 0
    full_urls: list[str] = []

    for position, entry in enumerate(bundle.entry):
        if entry.fullUrl:
            full_urls.append(entry.fullUrl)
        if entry.resource is None:
            unparsed += 1
            issues.add(
                IssueCode.RESOURCE_UNPARSEABLE,
                Severity.MEDIUM,
                f"Bundle entry at position {position} contains no resource.",
                path=f"Bundle.entry[{position}]",
            )
            continue

        resource_type = entry.resource.get("resourceType")
        if not isinstance(resource_type, str):
            unparsed += 1
            issues.add(
                IssueCode.RESOURCE_UNPARSEABLE,
                Severity.MEDIUM,
                f"Bundle entry at position {position} has no resourceType.",
                path=f"Bundle.entry[{position}].resource",
            )
            continue

        model = RESOURCE_MODELS.get(resource_type)
        if model is None:
            issues.add(
                IssueCode.RESOURCE_TYPE_UNSUPPORTED,
                Severity.LOW,
                f"Resource type '{resource_type}' is present in the bundle but is not "
                f"rendered by this application.",
                resource_type=resource_type,
                path=f"Bundle.entry[{position}].resource",
            )
            model = UnknownResource

        try:
            resource: DomainResource = model.model_validate(entry.resource)
        except ValidationError as exc:
            unparsed += 1
            issues.add(
                IssueCode.RESOURCE_UNPARSEABLE,
                Severity.HIGH,
                f"{resource_type} at position {position} failed validation and was "
                f"excluded: {exc.error_count()} error(s).",
                resource_type=resource_type,
                path=f"Bundle.entry[{position}].resource",
                detail={"errorCount": str(exc.error_count())},
            )
            continue

        index.add(resource, entry.fullUrl)

    _check_full_urls(full_urls, issues)
    _check_provenance(index, issues)

    return LoadedBundle(
        bundle=bundle,
        index=index,
        issues=issues,
        unparsed_entry_count=unparsed,
        full_urls=full_urls,
    )


def _check_bundle_structure(bundle: Bundle, issues: IssueLog) -> None:
    # FHIR R4 invariant bdl-1: total is only meaningful on searchset/history.
    if bundle.total is not None and bundle.type not in ("searchset", "history"):
        issues.add(
            IssueCode.BDL_TOTAL_ON_COLLECTION,
            Severity.LOW,
            f"Bundle.total is present on a '{bundle.type}' bundle. FHIR R4 invariant "
            f"bdl-1 permits total only on searchset or history bundles.",
            path="Bundle.total",
            detail={"bundleType": str(bundle.type)},
        )

    if bundle.total is not None and bundle.total != len(bundle.entry):
        issues.add(
            IssueCode.BDL_ENTRY_COUNT_MISMATCH,
            Severity.MEDIUM,
            f"Bundle.total is {bundle.total} but the bundle contains "
            f"{len(bundle.entry)} entries.",
            path="Bundle.total",
        )


def _check_full_urls(full_urls: list[str], issues: IssueLog) -> None:
    invalid_urns = [u for u in full_urls if u.startswith(_URN_UUID_PREFIX) and not _is_uuid(u)]
    if invalid_urns:
        issues.add(
            IssueCode.BDL_INVALID_UUID,
            Severity.LOW,
            f"{len(invalid_urns)} fullUrl value(s) use the urn:uuid: scheme with a "
            f"payload that is not a valid UUID (for example '{invalid_urns[0]}').",
            path="Bundle.entry.fullUrl",
            detail={"count": str(len(invalid_urns))},
        )

    counts = Counter(full_urls)
    duplicates = sorted(url for url, n in counts.items() if n > 1)
    if duplicates:
        issues.add(
            IssueCode.BDL_DUPLICATE_FULLURL,
            Severity.HIGH,
            f"Duplicate fullUrl value(s) in bundle: {', '.join(duplicates)}. "
            f"FHIR requires entry.fullUrl to be unique.",
            path="Bundle.entry.fullUrl",
        )


def _check_provenance(index: ResourceIndex, issues: IssueLog) -> None:
    has_provenance = bool(index.of_type("Provenance"))
    has_versioning = any(r.meta and (r.meta.versionId or r.meta.lastUpdated) for r in index.all())
    if not has_provenance and not has_versioning:
        issues.add(
            IssueCode.BDL_NO_PROVENANCE,
            Severity.MEDIUM,
            "No Provenance resources and no meta.versionId/meta.lastUpdated on any "
            "resource. The source system, author, and record recency are unknown.",
            path="Bundle",
        )


def _is_uuid(full_url: str) -> bool:
    try:
        uuid.UUID(full_url[len(_URN_UUID_PREFIX) :])
    except ValueError:
        return False
    return True
