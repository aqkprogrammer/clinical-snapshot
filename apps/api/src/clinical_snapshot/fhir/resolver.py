"""Reference resolution, and the policy decision it rests on.

## The problem

Every `fullUrl` in the supplied bundle is a URN (`urn:uuid:patient-001`) while
every reference between resources is relative (`Patient/patient-001`). FHIR
resolves a relative reference against the base established by the entry's
`fullUrl` -- and a `urn:` URI establishes no base. Read strictly, *none* of the
20 references in this bundle resolve.

Refusing to resolve any of them would be pedantically correct and produce a
useless snapshot. Resolving them without saying so would hide a real
structural defect in the feed.

## The policy

Three ordered steps, applied to every reference:

1. Exact `fullUrl` match.
2. `ResourceType/id` match against the index. This is the fallback that makes
   the bundle usable; taking it raises `BDL_REFERENCE_SCHEME_MISMATCH` once at
   bundle level so the defect is visible.
3. No match: return an unresolved result carrying the reason, and raise
   `REFERENCE_UNRESOLVED`.

Step 3 returns an object, never `None`. "This condition has no encounter" and
"this condition's encounter is not in the bundle" are different clinical
statements and must reach the UI as different things.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ..domain.issues import IssueCode, IssueLog, Severity
from .index import ResourceIndex
from .models import DomainResource, Reference


class ResolutionMethod(StrEnum):
    FULL_URL = "full-url"
    TYPE_ID_FALLBACK = "type-id-fallback"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True, slots=True)
class ResolvedReference:
    """The outcome of resolving one reference. Never discarded."""

    reference: str
    method: ResolutionMethod
    target: DomainResource | None = None
    reason: str | None = None

    @property
    def resolved(self) -> bool:
        return self.target is not None


class ReferenceResolver:
    def __init__(self, index: ResourceIndex, issues: IssueLog) -> None:
        self._index = index
        self._issues = issues
        self._used_fallback = False

    @property
    def used_type_id_fallback(self) -> bool:
        return self._used_fallback

    def resolve(
        self,
        reference: Reference | None,
        *,
        source_id: str | None = None,
        source_type: str | None = None,
        path: str | None = None,
    ) -> ResolvedReference | None:
        """Resolve a reference. Returns None only when there is no reference
        at all -- which means "the source recorded nothing here", as distinct
        from "the source pointed at something missing"."""
        if reference is None or not reference.reference:
            return None

        ref = reference.reference

        target = self._index.by_full_url(ref)
        if target is not None:
            return ResolvedReference(reference=ref, method=ResolutionMethod.FULL_URL, target=target)

        target = self._index.by_key(ref)
        if target is not None:
            self._used_fallback = True
            return ResolvedReference(
                reference=ref, method=ResolutionMethod.TYPE_ID_FALLBACK, target=target
            )

        self._issues.add(
            IssueCode.REFERENCE_UNRESOLVED,
            Severity.MEDIUM,
            f"Reference '{ref}' points to a resource that is not present in the bundle.",
            resource_id=source_id,
            resource_type=source_type,
            path=path,
            detail={"target": ref},
        )
        return ResolvedReference(
            reference=ref,
            method=ResolutionMethod.UNRESOLVED,
            reason="REFERENCE_TARGET_NOT_IN_BUNDLE",
        )
