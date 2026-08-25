"""Dates that remember how precise they are.

FHIR `date` and `dateTime` legitimately admit `YYYY`, `YYYY-MM`, `YYYY-MM-DD`
and full instants. The bundle uses all of them. The tempting fix --
`datetime.fromisoformat("2019")` fails, so pad it to `2019-01-01` -- invents a
January 1st onset that no clinician ever recorded.

So precision travels with the value. `value` is the source string, byte for
byte, and is the only thing ever rendered. Bounds are derived for sorting and
are deliberately not part of the rendered payload.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

# FHIR date / dateTime. Timezone is mandatory when a time is present.
_FHIR_DATE_TIME = re.compile(
    r"^(?P<year>\d{4})"
    r"(?:-(?P<month>0[1-9]|1[0-2])"
    r"(?:-(?P<day>0[1-9]|[12]\d|3[01])"
    r"(?:T(?P<hour>[01]\d|2[0-3]):(?P<minute>[0-5]\d):(?P<second>[0-5]\d|60)"
    r"(?P<fraction>\.\d+)?"
    r"(?P<tz>Z|[+-](?:0\d|1[0-3]):[0-5]\d|[+-]14:00)"
    r")?)?)?$"
)


class DatePrecision(StrEnum):
    """How much of the date the source actually told us."""

    YEAR = "year"
    MONTH = "month"
    DAY = "day"
    INSTANT = "instant"


@dataclass(frozen=True, slots=True)
class PartialDate:
    """A FHIR date/dateTime with its precision preserved.

    `value` is the source string unmodified. There is deliberately no method
    that returns a "best guess" full date -- callers that want to order values
    use `sort_key`, and callers that want to display one use `value` plus
    `precision`.
    """

    value: str
    precision: DatePrecision

    # -- construction ------------------------------------------------------

    @classmethod
    def parse(cls, raw: str | None) -> PartialDate | None:
        """Parse a FHIR date/dateTime. Returns None for absent or malformed input.

        Malformed is distinct from absent, but both mean "we have no usable
        date"; the caller decides which issue to raise.
        """
        if raw is None:
            return None
        match = _FHIR_DATE_TIME.match(raw.strip())
        if match is None:
            return None
        if match.group("hour") is not None:
            precision = DatePrecision.INSTANT
        elif match.group("day") is not None:
            precision = DatePrecision.DAY
        elif match.group("month") is not None:
            precision = DatePrecision.MONTH
        else:
            precision = DatePrecision.YEAR
        return cls(value=raw.strip(), precision=precision)

    # -- properties --------------------------------------------------------

    @property
    def is_reduced_precision(self) -> bool:
        """True when the source gave us less than a full calendar day.

        Note this is a statement about the *format* of the source string, not a
        heuristic about its content. `2018-01-01T00:00:00Z` is a full instant
        that happens to land on midnight on New Year's Day; it is not reduced
        precision and must not be reported as such.
        """
        return self.precision in (DatePrecision.YEAR, DatePrecision.MONTH)

    # -- ordering ----------------------------------------------------------

    @property
    def lower_bound(self) -> datetime:
        """Earliest instant this value could denote. For ordering only."""
        m = _FHIR_DATE_TIME.match(self.value)
        assert m is not None  # value was validated at construction
        if self.precision is DatePrecision.INSTANT:
            return datetime.fromisoformat(self.value.replace("Z", "+00:00"))
        year = int(m.group("year"))
        month = int(m.group("month") or 1)
        day = int(m.group("day") or 1)
        return datetime(year, month, day, tzinfo=UTC)

    @property
    def upper_bound(self) -> datetime:
        """First instant after the interval this value could denote.

        Exclusive. `2019` spans [2019-01-01, 2020-01-01).
        """
        lower = self.lower_bound
        if self.precision is DatePrecision.YEAR:
            return lower.replace(year=lower.year + 1)
        if self.precision is DatePrecision.MONTH:
            return (
                lower.replace(year=lower.year + 1, month=1)
                if lower.month == 12
                else lower.replace(month=lower.month + 1)
            )
        if self.precision is DatePrecision.DAY:
            return lower + timedelta(days=1)
        return lower

    def sort_key(self) -> tuple[datetime, datetime, str]:
        """Deterministic ordering by earliest possible instant.

        Ordering across mixed precision is inherently approximate: `2019`
        sorts as though it were the start of 2019 because that is the earliest
        moment it could mean. The precision travels with the value into the
        payload so the reader can see which orderings are soft.
        """
        return (self.lower_bound, self.upper_bound, self.value)

    def describe(self) -> str:
        """Human-readable form that never hides missing precision."""
        if self.precision is DatePrecision.YEAR:
            return f"{self.value} (year only)"
        if self.precision is DatePrecision.MONTH:
            return f"{self.value} (month only)"
        return self.value
