"""Standalone FHIR reference resolution.

## The problem this bundle poses

Every `fullUrl` in the supplied bundle is a URN (`urn:uuid:patient-001`) while
every reference between resources is relative (`Patient/patient-001`). FHIR
resolves a relative reference against the base established by the entry's
`fullUrl` -- and a `urn:` URI establishes no base. Read strictly, *none* of the
20 references in this bundle resolve.

Refusing all of them would be pedantically correct and produce an empty
snapshot. Resolving them silently would hide a real structural defect in the
feed. So the fallback is taken, and taking it is reported.

## Contract

`resolve()` always returns a `ResolutionResult`, never a bare `None`. Four
outcomes are distinguished, because they mean different things to a reader:

| Status | Meaning |
|---|---|
| `RESOLVED` | The target is in the bundle. |
| `UNRESOLVED` | Well-formed reference, target absent. *Unknown*, not *none*. |
| `TYPE_MISMATCH` | The reference points at the wrong kind of resource. |
| `MALFORMED` | The reference string is not a usable FHIR reference. |

Nothing is ever fabricated: an unresolved reference yields `target=None` and a
reason, and the original reference string is preserved byte for byte in every
outcome so the UI can show exactly what the source said.

This module is pure -- no issue log, no I/O. Callers translate results into
whatever reporting they need, which keeps the resolution rules testable in
isolation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from .index import BundleIndex
from .models import DomainResource, Reference

# FHIR resource type names are UpperCamelCase; ids are a restricted charset.
_RESOURCE_TYPE = re.compile(r"^[A-Z][A-Za-z]{1,254}$")
_RESOURCE_ID = re.compile(r"^[A-Za-z0-9\-.]{1,64}$")


class ReferenceKind(StrEnum):
    """The addressing form a reference string uses."""

    RELATIVE = "relative"
    ABSOLUTE = "absolute"
    URN = "urn"
    FRAGMENT = "fragment"


class ResolutionStatus(StrEnum):
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    TYPE_MISMATCH = "type-mismatch"
    MALFORMED = "malformed"


class ResolutionMethod(StrEnum):
    FULL_URL = "full-url"
    """Matched an entry's fullUrl exactly."""

    TYPE_ID = "type-id"
    """Matched ResourceType/id. Only correct under the documented fallback."""

    NONE = "none"


class ResolutionReason(StrEnum):
    TARGET_NOT_IN_BUNDLE = "REFERENCE_TARGET_NOT_IN_BUNDLE"
    MALFORMED_REFERENCE = "REFERENCE_MALFORMED"
    TYPE_MISMATCH = "REFERENCE_TYPE_MISMATCH"
    CONTAINED_UNSUPPORTED = "REFERENCE_CONTAINED_UNSUPPORTED"


@dataclass(frozen=True, slots=True)
class ParsedReference:
    """The addressable parts of a reference string, where they exist."""

    raw: str
    kind: ReferenceKind
    resource_type: str | None = None
    resource_id: str | None = None


@dataclass(frozen=True, slots=True)
class ResolutionResult:
    """The outcome of resolving one reference. Never discarded, never None."""

    reference: str
    """The source string, preserved exactly as written."""

    status: ResolutionStatus
    target: DomainResource | None = None
    method: ResolutionMethod = ResolutionMethod.NONE
    expected_type: str | None = None
    actual_type: str | None = None
    reason: ResolutionReason | None = None
    detail: str | None = None

    @property
    def resolved(self) -> bool:
        return self.status is ResolutionStatus.RESOLVED and self.target is not None

    @property
    def is_problem(self) -> bool:
        """True for anything a reader should be told about."""
        return self.status is not ResolutionStatus.RESOLVED


def parse_reference(raw: str) -> ParsedReference | None:
    """Split a reference string into its parts. None when unusable.

    Recognises the four forms FHIR permits: relative (`Patient/123`), absolute
    (`http://host/fhir/Patient/123`), URN (`urn:uuid:...`), and internal
    fragment (`#contained`). A `_history` suffix is accepted and discarded --
    version-specific addressing is not modelled here.
    """
    candidate = raw.strip()
    if not candidate or any(character.isspace() for character in candidate):
        return None

    if candidate.startswith("#"):
        return (
            ParsedReference(raw=raw, kind=ReferenceKind.FRAGMENT, resource_id=candidate[1:])
            if len(candidate) > 1
            else None
        )

    if candidate.startswith("urn:"):
        return ParsedReference(raw=raw, kind=ReferenceKind.URN) if len(candidate) > 4 else None

    kind = ReferenceKind.RELATIVE
    path = candidate
    if "://" in candidate:
        kind = ReferenceKind.ABSOLUTE
        path = candidate.split("://", 1)[1].split("/", 1)[-1]

    # Empty segments are not skipped: "Patient//123" is a malformed reference,
    # and quietly collapsing the double slash would resolve a broken string.
    segments = path.split("/")
    if any(segment == "" for segment in segments):
        return None
    if len(segments) >= 4 and segments[-2] == "_history":
        segments = segments[:-2]
    if len(segments) < 2:
        return None

    resource_type, resource_id = segments[-2], segments[-1]
    if not _RESOURCE_TYPE.match(resource_type) or not _RESOURCE_ID.match(resource_id):
        return None

    # A relative reference must be exactly Type/id -- extra leading segments
    # mean it is not the relative form it appears to be.
    if kind is ReferenceKind.RELATIVE and len(segments) != 2:
        return None

    return ParsedReference(
        raw=raw, kind=kind, resource_type=resource_type, resource_id=resource_id
    )


class ReferenceResolver:
    """Resolves references against a `BundleIndex`."""

    def __init__(self, index: BundleIndex) -> None:
        self._index = index
        self._used_type_id_fallback = False

    @property
    def used_type_id_fallback(self) -> bool:
        """Whether any reference resolved only via the ResourceType/id fallback.

        Bundle-level signal: when True, the feed addresses entries one way and
        references them another.
        """
        return self._used_type_id_fallback

    # -- public ------------------------------------------------------------

    def resolve(
        self, reference: Reference | str | None, *, expected_type: str | None = None
    ) -> ResolutionResult | None:
        """Resolve a reference.

        Returns `None` only when there is no reference at all -- which means
        "the source recorded nothing here", a different statement from "the
        source pointed at something missing". Every other case returns a
        structured result.
        """
        raw = reference.reference if isinstance(reference, Reference) else reference
        if raw is None or not raw.strip():
            return None

        parsed = parse_reference(raw)
        if parsed is None:
            return ResolutionResult(
                reference=raw,
                status=ResolutionStatus.MALFORMED,
                expected_type=expected_type,
                reason=ResolutionReason.MALFORMED_REFERENCE,
                detail=f"'{raw}' is not a usable FHIR reference.",
            )

        if parsed.kind is ReferenceKind.FRAGMENT:
            return ResolutionResult(
                reference=raw,
                status=ResolutionStatus.UNRESOLVED,
                expected_type=expected_type,
                reason=ResolutionReason.CONTAINED_UNSUPPORTED,
                detail=(
                    f"'{raw}' addresses a contained resource. Contained resources are "
                    f"not indexed by this application."
                ),
            )

        # A declared type that contradicts the expectation is a defect in the
        # reference itself, independent of whether the target exists.
        if expected_type and parsed.resource_type and parsed.resource_type != expected_type:
            return ResolutionResult(
                reference=raw,
                status=ResolutionStatus.TYPE_MISMATCH,
                expected_type=expected_type,
                actual_type=parsed.resource_type,
                reason=ResolutionReason.TYPE_MISMATCH,
                detail=(
                    f"'{raw}' declares type '{parsed.resource_type}' but a "
                    f"'{expected_type}' was expected."
                ),
            )

        target, method = self._lookup(raw, parsed)
        if target is None:
            return ResolutionResult(
                reference=raw,
                status=ResolutionStatus.UNRESOLVED,
                expected_type=expected_type,
                actual_type=parsed.resource_type,
                reason=ResolutionReason.TARGET_NOT_IN_BUNDLE,
                detail=f"'{raw}' points to a resource that is not present in the bundle.",
            )

        if expected_type and target.resourceType != expected_type:
            return ResolutionResult(
                reference=raw,
                status=ResolutionStatus.TYPE_MISMATCH,
                target=None,
                method=method,
                expected_type=expected_type,
                actual_type=target.resourceType,
                reason=ResolutionReason.TYPE_MISMATCH,
                detail=(
                    f"'{raw}' resolves to a '{target.resourceType}' but a "
                    f"'{expected_type}' was expected."
                ),
            )

        if method is ResolutionMethod.TYPE_ID:
            self._used_type_id_fallback = True

        return ResolutionResult(
            reference=raw,
            status=ResolutionStatus.RESOLVED,
            target=target,
            method=method,
            expected_type=expected_type,
            actual_type=target.resourceType,
        )

    # -- internals ---------------------------------------------------------

    def _lookup(
        self, raw: str, parsed: ParsedReference
    ) -> tuple[DomainResource | None, ResolutionMethod]:
        """Ordered resolution policy. Exact addressing first, fallback second."""
        exact = self._index.get_by_full_url(raw.strip())
        if exact is not None:
            return exact, ResolutionMethod.FULL_URL

        if parsed.resource_type and parsed.resource_id:
            by_key = self._index.get(parsed.resource_type, parsed.resource_id)
            if by_key is not None:
                return by_key, ResolutionMethod.TYPE_ID

        return None, ResolutionMethod.NONE
