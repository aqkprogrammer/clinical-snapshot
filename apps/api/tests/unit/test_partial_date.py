"""PartialDate must preserve precision exactly. These tests are the guard
against the single most tempting bug in this codebase: padding `2019` out to
`2019-01-01` so that `datetime.fromisoformat` stops complaining.
"""

from datetime import UTC, datetime

import pytest

from clinical_snapshot.domain.partial_date import DatePrecision, PartialDate


class TestParsing:
    @pytest.mark.parametrize(
        ("raw", "precision"),
        [
            ("2019", DatePrecision.YEAR),
            ("1958", DatePrecision.YEAR),
            ("2019-06", DatePrecision.MONTH),
            ("1958-03-12", DatePrecision.DAY),
            ("2025-11-04T14:12:00Z", DatePrecision.INSTANT),
            ("2025-11-04T14:12:00.500Z", DatePrecision.INSTANT),
            ("2025-11-04T14:12:00+05:30", DatePrecision.INSTANT),
        ],
    )
    def test_detects_precision(self, raw: str, precision: DatePrecision) -> None:
        parsed = PartialDate.parse(raw)
        assert parsed is not None
        assert parsed.precision is precision

    def test_value_is_preserved_byte_for_byte(self) -> None:
        for raw in ["2019", "1958-03-12", "2025-11-04T14:12:00Z"]:
            parsed = PartialDate.parse(raw)
            assert parsed is not None
            assert parsed.value == raw

    @pytest.mark.parametrize(
        "raw",
        [
            None,
            "",
            "not-a-date",
            "19",
            "2019-13",           # month out of range
            "2019-06-32",        # day out of range
            "2025-11-04T14:12",  # seconds required
            "2025-11-04T14:12:00",  # FHIR requires a timezone when time present
        ],
    )
    def test_rejects_malformed(self, raw: str | None) -> None:
        assert PartialDate.parse(raw) is None


class TestReducedPrecision:
    def test_year_and_month_are_reduced(self) -> None:
        for raw in ["2019", "2016", "2019-06"]:
            parsed = PartialDate.parse(raw)
            assert parsed is not None
            assert parsed.is_reduced_precision

    def test_day_and_instant_are_not_reduced(self) -> None:
        for raw in ["1958-03-12", "2025-11-04T14:12:00Z"]:
            parsed = PartialDate.parse(raw)
            assert parsed is not None
            assert not parsed.is_reduced_precision

    def test_midnight_instants_are_not_reduced_precision(self) -> None:
        """A full timestamp that lands on midnight is fully precise.

        The bundle contains `2018-01-01T00:00:00Z` and `2015-04-11T00:00:00Z`.
        A "looks like a placeholder" heuristic would wrongly flag these.
        """
        for raw in ["2018-01-01T00:00:00Z", "2015-04-11T00:00:00Z"]:
            parsed = PartialDate.parse(raw)
            assert parsed is not None
            assert parsed.precision is DatePrecision.INSTANT
            assert not parsed.is_reduced_precision


class TestBounds:
    def test_year_bounds_span_the_whole_year(self) -> None:
        parsed = PartialDate.parse("2019")
        assert parsed is not None
        assert parsed.lower_bound == datetime(2019, 1, 1, tzinfo=UTC)
        assert parsed.upper_bound == datetime(2020, 1, 1, tzinfo=UTC)

    def test_december_month_rolls_into_next_year(self) -> None:
        parsed = PartialDate.parse("2019-12")
        assert parsed is not None
        assert parsed.upper_bound == datetime(2020, 1, 1, tzinfo=UTC)

    def test_instant_bounds_collapse(self) -> None:
        parsed = PartialDate.parse("2025-11-04T14:12:00Z")
        assert parsed is not None
        assert parsed.lower_bound == parsed.upper_bound

    def test_bounds_never_leak_into_value(self) -> None:
        """Deriving bounds must not mutate or upgrade the rendered value."""
        parsed = PartialDate.parse("2019")
        assert parsed is not None
        _ = parsed.lower_bound, parsed.upper_bound, parsed.sort_key()
        assert parsed.value == "2019"
        assert parsed.precision is DatePrecision.YEAR


class TestOrdering:
    def test_sorts_by_earliest_possible_instant(self) -> None:
        raws = ["2022", "2019", "2025-11-04T14:12:00Z", "1958-03-12"]
        parsed = [p for p in (PartialDate.parse(r) for r in raws) if p is not None]
        ordered = sorted(parsed, key=lambda p: p.sort_key())
        assert [p.value for p in ordered] == [
            "1958-03-12",
            "2019",
            "2022",
            "2025-11-04T14:12:00Z",
        ]

    def test_ordering_is_deterministic_for_equal_lower_bounds(self) -> None:
        year = PartialDate.parse("2019")
        day = PartialDate.parse("2019-01-01")
        assert year is not None and day is not None
        assert year.lower_bound == day.lower_bound
        # the year spans a wider interval, so it sorts after the precise day
        assert day.sort_key() < year.sort_key()


class TestDescribe:
    def test_flags_low_precision_in_text(self) -> None:
        year = PartialDate.parse("2019")
        assert year is not None
        assert year.describe() == "2019 (year only)"

    def test_leaves_full_precision_alone(self) -> None:
        day = PartialDate.parse("1958-03-12")
        assert day is not None
        assert day.describe() == "1958-03-12"


class TestParsedValueWhereSafe:
    """"Where safe" is the whole point: year and month precision yield no
    calendar date at all, because every candidate would be invented."""

    def test_year_precision_yields_no_parsed_date(self) -> None:
        parsed = PartialDate.parse("2019")
        assert parsed is not None
        assert parsed.parsed_date is None
        assert parsed.parsed_instant is None

    def test_month_precision_yields_no_parsed_date(self) -> None:
        parsed = PartialDate.parse("2019-07")
        assert parsed is not None
        assert parsed.parsed_date is None
        assert parsed.parsed_instant is None

    def test_day_precision_yields_a_date_but_no_instant(self) -> None:
        from datetime import date

        parsed = PartialDate.parse("1958-03-12")
        assert parsed is not None
        assert parsed.parsed_date == date(1958, 3, 12)
        assert parsed.parsed_instant is None

    def test_instant_yields_both(self) -> None:
        from datetime import date

        parsed = PartialDate.parse("2025-11-04T14:12:00Z")
        assert parsed is not None
        assert parsed.parsed_date == date(2025, 11, 4)
        assert parsed.parsed_instant == datetime(2025, 11, 4, 14, 12, tzinfo=UTC)

    def test_parsed_instant_is_always_timezone_aware(self) -> None:
        for raw in ["2025-11-04T14:12:00Z", "2025-11-04T14:12:00+05:30"]:
            parsed = PartialDate.parse(raw)
            assert parsed is not None
            assert parsed.parsed_instant is not None
            assert parsed.parsed_instant.tzinfo is not None

    def test_offset_is_respected_not_discarded(self) -> None:
        aware = PartialDate.parse("2025-11-04T14:12:00+05:30")
        utc = PartialDate.parse("2025-11-04T08:42:00Z")
        assert aware is not None and utc is not None
        assert aware.parsed_instant == utc.parsed_instant

    def test_display_never_exceeds_source_precision(self) -> None:
        for raw, expected in [
            ("2019", "2019 (year only)"),
            ("2019-07", "2019-07 (month only)"),
            ("1958-03-12", "1958-03-12"),
        ]:
            parsed = PartialDate.parse(raw)
            assert parsed is not None
            assert parsed.display == expected
