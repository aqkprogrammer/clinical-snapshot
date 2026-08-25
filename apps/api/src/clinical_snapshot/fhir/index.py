"""In-memory index of the resources parsed out of a bundle."""

from __future__ import annotations

from collections import defaultdict

from .models import DomainResource


class ResourceIndex:
    """Lookup by `fullUrl`, by `ResourceType/id`, and by type.

    Both key spaces are kept because the bundle populates them
    inconsistently: entries are addressed by URN `fullUrl` while references
    between them are relative. See `resolver.py`.
    """

    def __init__(self) -> None:
        self._by_full_url: dict[str, DomainResource] = {}
        self._by_key: dict[str, DomainResource] = {}
        self._by_type: dict[str, list[DomainResource]] = defaultdict(list)
        self._order: list[DomainResource] = []

    def add(self, resource: DomainResource, full_url: str | None) -> None:
        if full_url:
            self._by_full_url[full_url] = resource
        if resource.id:
            self._by_key[resource.key] = resource
        self._by_type[resource.resourceType].append(resource)
        self._order.append(resource)

    def by_full_url(self, full_url: str) -> DomainResource | None:
        return self._by_full_url.get(full_url)

    def by_key(self, key: str) -> DomainResource | None:
        return self._by_key.get(key)

    def of_type(self, resource_type: str) -> list[DomainResource]:
        return list(self._by_type.get(resource_type, []))

    def all(self) -> list[DomainResource]:
        """Every indexed resource, in bundle order."""
        return list(self._order)

    def __len__(self) -> int:
        return len(self._order)
