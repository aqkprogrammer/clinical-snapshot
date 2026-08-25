"""The Observation renderability rule.

The rule is *stated*, not counted: withhold only when the analyte cannot be
named AND the measurement cannot be classified. The previous implementation
counted blockers and routed on `>= 2`, which conflated "cannot be identified"
with "identifiable but recorded to year precision".
"""

from __future__ import annotations

import pytest

from clinical_snapshot.domain.partial_date import PartialDate
from clinical_snapshot.domain.renderability import (
    LOW_DATE_PRECISION,
    UNCLASSIFIABLE,
    UNNAMEABLE,
    Renderability,
    assess_observation,
)
from clinical_snapshot.domain.terminology import DisplaySource, DisplayStatus, ResolvedCoding
from clinical_snapshot.domain.views import ObservationView, Provenance

PROVENANCE = Provenance("observation-x", "RULE_OBSERVATION_CURRENT")


def coding(*, resolved: bool) -> ResolvedCoding:
    return ResolvedCoding(
        system="http://loinc.org",
        code="4548-4",
        display="Haemoglobin A1c" if resolved else None,
        display_status=DisplayStatus.FROM_SOURCE if resolved else DisplayStatus.UNRESOLVED,
        system_name="LOINC",
        display_source=DisplaySource.FHIR if resolved else DisplaySource.UNAVAILABLE,
    )


def view(
    *,
    nameable: bool = True,
    category: str | None = "laboratory",
    date: str | None = "2025-11-04T14:15:00Z",
) -> ObservationView:
    return ObservationView(
        id="observation-x",
        code=coding(resolved=nameable),
        category_declared=category,
        effective=PartialDate.parse(date),
        value=6.1,
        unit="%",
        components=(),
        performer=None,
        encounter=None,
        reference_range_available=False,
        interpretation_available=False,
        flags=(),
        provenance=PROVENANCE,
    )


class TestTheRule:
    def test_nameable_and_classifiable_renders(self) -> None:
        assert assess_observation(view()).renderable is True

    def test_unnameable_but_classifiable_still_renders(self) -> None:
        """'LOINC 4548-4 — display unavailable' in a laboratory section still
        tells the reader what kind of measurement it is."""
        verdict = assess_observation(view(nameable=False))
        assert verdict.renderable is True
        assert verdict.blockers == (UNNAMEABLE,)

    def test_nameable_but_unclassifiable_still_renders(self) -> None:
        """'Body weight, 71.2 kg, category not declared' is perfectly readable."""
        verdict = assess_observation(view(category=None))
        assert verdict.renderable is True
        assert verdict.blockers == (UNCLASSIFIABLE,)

    def test_neither_nameable_nor_classifiable_is_withheld(self) -> None:
        verdict = assess_observation(view(nameable=False, category=None))
        assert verdict.renderable is False
        assert verdict.blockers == (UNNAMEABLE, UNCLASSIFIABLE)


class TestDatePrecisionIsACaveatNotABlocker:
    def test_low_precision_alone_never_withholds(self) -> None:
        verdict = assess_observation(view(date="2020"))
        assert verdict.renderable is True
        assert verdict.caveats == (LOW_DATE_PRECISION,)
        assert verdict.blockers == ()

    def test_low_precision_plus_one_blocker_still_renders(self) -> None:
        """The behaviour that changed.

        Under the old `len(blockers) >= 2` rule this was withheld, because date
        precision was counted alongside the real blockers -- so a nameable,
        classifiable observation with a year-only date was treated as
        unidentifiable.
        """
        verdict = assess_observation(view(nameable=False, date="2020"))
        assert verdict.renderable is True
        assert verdict.blockers == (UNNAMEABLE,)
        assert LOW_DATE_PRECISION in verdict.caveats

    def test_low_precision_plus_one_blocker_the_other_way(self) -> None:
        verdict = assess_observation(view(category=None, date="2020"))
        assert verdict.renderable is True

    @pytest.mark.parametrize("date", ["2025-11-04T14:15:00Z", "1958-03-12"])
    def test_full_precision_raises_no_caveat(self, date: str) -> None:
        assert assess_observation(view(date=date)).caveats == ()

    def test_a_midnight_instant_is_not_low_precision(self) -> None:
        """A full timestamp landing on midnight is fully precise."""
        assert assess_observation(view(date="2018-01-01T00:00:00Z")).caveats == ()

    def test_absent_date_raises_no_caveat(self) -> None:
        assert assess_observation(view(date=None)).caveats == ()


class TestReasons:
    def test_reasons_lead_with_blockers_then_caveats(self) -> None:
        verdict = assess_observation(view(nameable=False, category=None, date="2020"))
        assert verdict.reasons == (UNNAMEABLE, UNCLASSIFIABLE, LOW_DATE_PRECISION)

    def test_a_fully_identified_observation_has_no_reasons(self) -> None:
        assert assess_observation(view()).reasons == ()

    def test_caveats_are_reported_even_when_renderable(self) -> None:
        """The reader still needs to know the date is year-precision."""
        assert assess_observation(view(date="2020")).reasons == (LOW_DATE_PRECISION,)


class TestPurity:
    def test_assessment_is_deterministic(self) -> None:
        target = view(nameable=False, category=None, date="2020")
        assert len({assess_observation(target) for _ in range(20)}) == 1

    def test_renderability_is_a_value_object(self) -> None:
        verdict = Renderability(unnameable=True, unclassifiable=False)
        with pytest.raises(AttributeError):
            verdict.unnameable = False  # type: ignore[misc]
