"""Addressable index over the resources in a bundle.

Everything that needs to find a resource goes through here, so lookup rules
live in one place and behave identically for every caller.

Three properties the rest of the application depends on:

**Deterministic.** Bundle order is preserved everywhere. When two entries
compete for the same address, the earlier one wins -- always, and the choice is
reported rather than assumed.

**Non-destructive.** A duplicate never overwrites its predecessor. Both are
retained and both are retrievable via `candidates()`. Overwriting would make
the second copy of a resource invisible, and "invisible" and "absent" are
indistinguishable to whoever reads the output.

**Structural only.** This layer knows about `resourceType`, `id`, `fullUrl` and
reference strings. It makes no judgement about clinical status, currency, or
safety -- that is `domain/safety.py`'s job. Nothing here filters a resource out
for clinical reasons.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from enum import StrEnum

from .models import DomainResource, Patient, Reference

# The reference elements by which a resource names its subject. Structural
# FHIR, not a clinical judgement: these are simply where the spec puts it.
_SUBJECT_ELEMENTS = ("subject", "patient")


class IndexConflictKind(StrEnum):
    """Ways a bundle can be ambiguous about how a resource is addressed."""

    DUPLICATE_KEY = "duplicate-key"
    """Two entries share a ResourceType/id. Only one can answer a lookup."""

    DUPLICATE_FULL_URL = "duplicate-full-url"
    """Two entries share a fullUrl. FHIR requires these to be unique."""

    MISSING_ID = "missing-id"
    """A resource has no id, so it cannot be addressed by key at all."""


@dataclass(frozen=True, slots=True)
class IndexedResource:
    """A resource plus how it is addressed within its bundle."""

    resource: DomainResource
    position: int
    """Zero-based index in Bundle.entry. The tiebreaker for every conflict."""

    full_url: str | None = None

    @property
    def resource_type(self) -> str:
        return self.resource.resourceType

    @property
    def key(self) -> str | None:
        """`ResourceType/id`, or None when the resource carries no id."""
        return f"{self.resource.resourceType}/{self.resource.id}" if self.resource.id else None


@dataclass(frozen=True, slots=True)
class IndexConflict:
    """A reported ambiguity. Never raised -- the caller decides what it means."""

    kind: IndexConflictKind
    resource_type: str
    message: str
    key: str | None = None
    full_url: str | None = None
    positions: tuple[int, ...] = field(default_factory=tuple)
    retained_position: int | None = None
    """Which entry answers lookups for this address. None when nothing can."""

    @property
    def shadowed_positions(self) -> tuple[int, ...]:
        """Entries that exist but are not reachable by this address."""
        return tuple(p for p in self.positions if p != self.retained_position)


@dataclass(frozen=True, slots=True)
class IndexReport:
    """What the index learned while being built."""

    conflicts: tuple[IndexConflict, ...] = field(default_factory=tuple)
    indexed_count: int = 0
    addressable_count: int = 0
    """Resources reachable by ResourceType/id. Never more than indexed_count."""

    @property
    def has_conflicts(self) -> bool:
        return bool(self.conflicts)

    def of_kind(self, kind: IndexConflictKind) -> tuple[IndexConflict, ...]:
        return tuple(c for c in self.conflicts if c.kind is kind)


class BundleIndex:
    """Addressable, conflict-reporting index over one bundle's resources."""

    def __init__(self) -> None:
        self._entries: list[IndexedResource] = []
        self._by_key: dict[str, list[IndexedResource]] = defaultdict(list)
        self._by_full_url: dict[str, list[IndexedResource]] = defaultdict(list)
        self._by_type: dict[str, list[IndexedResource]] = defaultdict(list)
        self._by_subject: dict[str, list[IndexedResource]] = defaultdict(list)
        self._missing_id: list[IndexedResource] = []

    # -- construction ------------------------------------------------------

    @classmethod
    def build(cls, resources: list[tuple[DomainResource, str | None]]) -> BundleIndex:
        """Index `(resource, fullUrl)` pairs in bundle order."""
        index = cls()
        for resource, full_url in resources:
            index.add(resource, full_url)
        return index

    def add(self, resource: DomainResource, full_url: str | None = None) -> IndexedResource:
        """Index one resource. Never rejects, never overwrites."""
        entry = IndexedResource(
            resource=resource, position=len(self._entries), full_url=full_url
        )
        self._entries.append(entry)
        self._by_type[entry.resource_type].append(entry)

        if entry.key is None:
            self._missing_id.append(entry)
        else:
            self._by_key[entry.key].append(entry)

        if full_url:
            self._by_full_url[full_url].append(entry)

        subject = self._subject_reference(resource)
        if subject:
            self._by_subject[subject].append(entry)

        return entry

    # -- lookup ------------------------------------------------------------

    def get(self, resource_type: str, resource_id: str) -> DomainResource | None:
        """Resource for `ResourceType/id`, or None. First occurrence wins."""
        return self.get_by_key(f"{resource_type}/{resource_id}")

    def get_by_key(self, key: str) -> DomainResource | None:
        entries = self._by_key.get(key)
        return entries[0].resource if entries else None

    def get_by_full_url(self, full_url: str) -> DomainResource | None:
        entries = self._by_full_url.get(full_url)
        return entries[0].resource if entries else None

    def candidates(self, key: str) -> tuple[DomainResource, ...]:
        """Every resource claiming `key`, in bundle order.

        Length > 1 means a `DUPLICATE_KEY` conflict was reported. The shadowed
        copies are reachable here so a caller can compare them rather than
        having to trust that the first one was the right one.
        """
        return tuple(entry.resource for entry in self._by_key.get(key, []))

    def of_type(self, resource_type: str) -> list[DomainResource]:
        """Every resource of a type, in bundle order, duplicates included."""
        return [entry.resource for entry in self._by_type.get(resource_type, [])]

    def patients(self) -> list[Patient]:
        return [
            e.resource
            for e in self._by_type.get("Patient", [])
            if isinstance(e.resource, Patient)
        ]

    def all(self) -> list[DomainResource]:
        return [entry.resource for entry in self._entries]

    def entries(self) -> list[IndexedResource]:
        """Indexed entries with their positions and fullUrls."""
        return list(self._entries)

    def resource_types(self) -> list[str]:
        return sorted(self._by_type)

    # -- patient association -----------------------------------------------

    def aliases_for(self, resource: DomainResource) -> tuple[str, ...]:
        """Every string by which this resource can legitimately be referenced.

        A bundle may address an entry by URN `fullUrl` while its siblings refer
        to it relatively, so both forms are valid addresses for the same thing.
        """
        aliases: list[str] = []
        for entry in self._entries:
            if entry.resource is resource:
                if entry.key:
                    aliases.append(entry.key)
                if entry.full_url:
                    aliases.append(entry.full_url)
        return tuple(dict.fromkeys(aliases))

    def for_patient_reference(self, reference: str) -> list[DomainResource]:
        """Resources naming `reference` as their subject or patient.

        Purely a string match against `subject.reference` / `patient.reference`,
        widened to the referenced patient's other aliases when the reference
        resolves inside this bundle. No status filtering happens here.
        """
        keys = [reference]
        target = self.get_by_key(reference) or self.get_by_full_url(reference)
        if target is not None:
            keys.extend(self.aliases_for(target))

        seen: set[int] = set()
        matched: list[tuple[int, DomainResource]] = []
        for key in dict.fromkeys(keys):
            for entry in self._by_subject.get(key, []):
                if entry.position not in seen:
                    seen.add(entry.position)
                    matched.append((entry.position, entry.resource))
        matched.sort(key=lambda pair: pair[0])
        return [resource for _, resource in matched]

    def for_patient(self, patient: Patient) -> list[DomainResource]:
        """Resources whose subject is this Patient, in bundle order."""
        aliases = self.aliases_for(patient)
        return self.for_patient_reference(aliases[0]) if aliases else []

    # -- reporting ---------------------------------------------------------

    def report(self) -> IndexReport:
        """Conflicts found while indexing. Deterministic for a given bundle."""
        conflicts: list[IndexConflict] = []

        for key in sorted(self._by_key):
            entries = self._by_key[key]
            if len(entries) > 1:
                positions = tuple(e.position for e in entries)
                conflicts.append(
                    IndexConflict(
                        kind=IndexConflictKind.DUPLICATE_KEY,
                        resource_type=entries[0].resource_type,
                        key=key,
                        positions=positions,
                        retained_position=positions[0],
                        message=(
                            f"{len(entries)} entries share the address '{key}' "
                            f"(bundle positions {', '.join(map(str, positions))}). The entry "
                            f"at position {positions[0]} answers lookups; the others are "
                            f"retained and reachable via candidates() but are not addressable."
                        ),
                    )
                )

        for full_url in sorted(self._by_full_url):
            entries = self._by_full_url[full_url]
            if len(entries) > 1:
                positions = tuple(e.position for e in entries)
                conflicts.append(
                    IndexConflict(
                        kind=IndexConflictKind.DUPLICATE_FULL_URL,
                        resource_type=entries[0].resource_type,
                        full_url=full_url,
                        positions=positions,
                        retained_position=positions[0],
                        message=(
                            f"{len(entries)} entries share fullUrl '{full_url}' (bundle "
                            f"positions {', '.join(map(str, positions))}). FHIR requires "
                            f"Bundle.entry.fullUrl to be unique."
                        ),
                    )
                )

        for entry in self._missing_id:
            conflicts.append(
                IndexConflict(
                    kind=IndexConflictKind.MISSING_ID,
                    resource_type=entry.resource_type,
                    full_url=entry.full_url,
                    positions=(entry.position,),
                    retained_position=None,
                    message=(
                        f"{entry.resource_type} at bundle position {entry.position} has no "
                        f"id and cannot be addressed by ResourceType/id. It is still "
                        f"listed by of_type() and all()."
                    ),
                )
            )

        return IndexReport(
            conflicts=tuple(conflicts),
            indexed_count=len(self._entries),
            addressable_count=sum(len(v) for v in self._by_key.values()),
        )

    # -- internals ---------------------------------------------------------

    @staticmethod
    def _subject_reference(resource: DomainResource) -> str | None:
        for element in _SUBJECT_ELEMENTS:
            value = getattr(resource, element, None)
            if isinstance(value, Reference) and value.reference:
                return value.reference
        return None

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and key in self._by_key
