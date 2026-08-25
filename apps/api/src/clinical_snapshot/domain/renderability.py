"""Whether an Observation can honestly be shown as a clinical result.

This is a *completeness* question, not a record-status one, which is why it
lives here rather than in `safety.py`. A `final` Observation is safe to display
as current — but that says nothing about whether the reader will be able to
tell what they are looking at.

The rule is deliberately narrow, and stated rather than counted:

    An Observation is withheld from the clinical sections only when it is
    **both unnameable and unclassifiable** — no resolvable display for its
    code, *and* no category. In that state all we have is a bare number, and
    rendering it invites the reader to supply a meaning we do not have.

Anything less than both still renders, with the caveat attached:

  * *Unnameable but classifiable* — "LOINC 4548-4 — display unavailable" in a
    laboratory section still tells the reader what kind of measurement it is
    and that the analyte is unknown. That is more information than hiding it.
  * *Nameable but unclassifiable* — "Body weight, 71.2 kg, category not
    declared" is perfectly readable.

Low date precision is a **caveat, never a blocker**. It changes how a value
should be read, not whether it can be. An earlier version of this rule counted
blockers and routed on `len(blockers) >= 2`, which made a nameable,
classifiable observation with a year-only date indistinguishable from one that
could not be identified at all.
"""

from __future__ import annotations

from dataclasses import dataclass

from .terminology import DisplayStatus
from .views import ObservationView

UNNAMEABLE = "TERMINOLOGY_DISPLAY_UNRESOLVED"
UNCLASSIFIABLE = "OBSERVATION_CATEGORY_ABSENT"
LOW_DATE_PRECISION = "DATE_PRECISION_REDUCED"


@dataclass(frozen=True, slots=True)
class Renderability:
    """Why an Observation can or cannot be presented as a result."""

    unnameable: bool
    """No resolvable display for the observation's code."""

    unclassifiable: bool
    """No `Observation.category`, so the kind of measurement is unknown."""

    caveats: tuple[str, ...] = ()
    """Facts that qualify how the value should be read, but do not block it."""

    @property
    def renderable(self) -> bool:
        """False only when the analyte cannot be named *and* the measurement
        cannot be classified."""
        return not (self.unnameable and self.unclassifiable)

    @property
    def blockers(self) -> tuple[str, ...]:
        codes: list[str] = []
        if self.unnameable:
            codes.append(UNNAMEABLE)
        if self.unclassifiable:
            codes.append(UNCLASSIFIABLE)
        return tuple(codes)

    @property
    def reasons(self) -> tuple[str, ...]:
        """Everything worth telling the reader: blockers first, then caveats."""
        return (*self.blockers, *self.caveats)


def assess_observation(view: ObservationView) -> Renderability:
    """Assess one Observation view. Pure."""
    caveats: list[str] = []
    if view.effective is not None and view.effective.is_reduced_precision:
        caveats.append(LOW_DATE_PRECISION)
    return Renderability(
        unnameable=view.code.display_status is DisplayStatus.UNRESOLVED,
        unclassifiable=view.category_declared is None,
        caveats=tuple(caveats),
    )
