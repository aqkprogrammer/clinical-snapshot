"""Patient identity: producing evidence, not a merge.

The bundle contains two Patient resources that look like the same woman. They
share a surname, a first name, a sex, a normalised street address, and a birth
year. The obvious move is to merge them.

Do not. A merge would pull `medicationrequest-003` -- an *active* order whose
RxNorm code carries no display, so the drug cannot even be named -- into the
other patient's medication list. If the two records are not the same person,
that is a medication-reconciliation error introduced by the application itself.

What the source system actually asserts is the opposite of a match:

  * The two MRNs are *different values in the same assigning system*. One
    system issuing two identifiers is that system asserting two identities.
  * Neither Patient carries a `Patient.link`. FHIR provides `replaced-by`,
    `replaces`, `refer` and `seealso` precisely so a source can say "these are
    the same person". This source declined to.
  * The only high-entropy identifier available (an SSN) exists on one record
    only, so it cannot be cross-checked.
  * The birth dates agree only because one of them is year-precision. A
    day-level match was never established.

Same surname plus same address is also the textbook false-positive in master
patient index work -- two relatives in one household. Nothing here excludes it.

So this module scores evidence in both directions, records which side each
signal falls on, and stops. `merge_performed` is False unless the *source*
asserted a link. The presentation layer shows one patient, discloses the other
record's clinical data under an explicit attribution, and leaves the identity
question open for a human.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

from ..fhir.models import Address, Patient
from .issues import IssueCode, IssueLog, Severity
from .partial_date import DatePrecision, PartialDate

SSN_SYSTEM = "http://hl7.org/fhir/sid/us-ssn"

# Identifier systems whose values are high-entropy enough that an exact match
# is meaningful on its own.
_STRONG_IDENTIFIER_SYSTEMS = frozenset({SSN_SYSTEM})

_STREET_SUFFIXES = {
    "ln": "lane", "st": "street", "ave": "avenue", "av": "avenue", "rd": "road",
    "dr": "drive", "blvd": "boulevard", "ct": "court", "pl": "place",
    "sq": "square", "ter": "terrace", "pkwy": "parkway", "cir": "circle",
    "hwy": "highway", "trl": "trail", "way": "way",
}

_PUNCTUATION = re.compile(r"[^a-z0-9\s]")
_WHITESPACE = re.compile(r"\s+")


class EvidenceDirection(StrEnum):
    FOR = "for"
    AGAINST = "against"


class EvidenceStrength(StrEnum):
    DECISIVE = "decisive"
    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"
    VERY_WEAK = "very-weak"
    SUGGESTIVE_ONLY = "suggestive-only"
    BLOCKS_CONFIRMATION = "blocks-confirmation"
    NEUTRAL = "neutral"


class Determination(StrEnum):
    SOURCE_ASSERTED_LINK = "source-asserted-link"
    """The source used Patient.link. We follow the source's assertion."""

    UNRECONCILED = "unreconciled"
    """Demographics overlap but nothing confirms identity. No merge."""

    DISTINCT = "distinct"
    """Positive evidence the records are different people."""


@dataclass(frozen=True, slots=True)
class Evidence:
    signal: str
    detail: str
    strength: EvidenceStrength
    direction: EvidenceDirection


@dataclass(frozen=True, slots=True)
class CrossRecordResource:
    """A clinical resource attached to a non-primary candidate record.

    Surfaced explicitly rather than merged in or dropped. Hiding an active
    medication is as much a safety failure as misattributing one.
    """

    resource_id: str
    resource_type: str
    status: str | None
    patient_id: str
    note: str


@dataclass(frozen=True, slots=True)
class DuplicateCandidate:
    candidate_id: str
    member_ids: tuple[str, ...]
    determination: Determination
    merge_performed: bool
    source_asserted_link: str | None
    evidence_for: tuple[Evidence, ...]
    evidence_against: tuple[Evidence, ...]
    cross_record_resources: tuple[CrossRecordResource, ...] = field(default_factory=tuple)
    recommended_action: str = "human-steward-review"


@dataclass(frozen=True, slots=True)
class IdentityAnalysis:
    primary_patient_id: str | None
    primary_selection_rationale: str
    all_patient_ids: tuple[str, ...]
    candidates: tuple[DuplicateCandidate, ...]

    def candidate_for(self, patient_id: str) -> DuplicateCandidate | None:
        return next((c for c in self.candidates if patient_id in c.member_ids), None)


# --------------------------------------------------------------------------
# Normalisation helpers
# --------------------------------------------------------------------------


def _normalise_text(value: str | None) -> str:
    if not value:
        return ""
    lowered = _PUNCTUATION.sub(" ", value.lower())
    return _WHITESPACE.sub(" ", lowered).strip()


def normalise_address(address: Address | None) -> str:
    """Conservative postal normalisation: case, punctuation, and the common
    street-suffix abbreviations. Deliberately does not attempt unit numbers or
    directional prefixes -- an over-eager normaliser manufactures matches."""
    if address is None:
        return ""
    parts = [
        " ".join(_STREET_SUFFIXES.get(token, token) for token in _normalise_text(line).split())
        for line in address.line
    ]
    parts.extend(
        _normalise_text(v) for v in (address.city, address.state, address.postalCode)
    )
    return ", ".join(p for p in parts if p)


# --------------------------------------------------------------------------
# Pairwise comparison
# --------------------------------------------------------------------------


def _compare_links(a: Patient, b: Patient) -> tuple[list[Evidence], str | None]:
    """The only signal that can authorise a merge."""
    for source, target in ((a, b), (b, a)):
        for link in source.link:
            ref = link.other.reference if link.other else None
            if ref and target.id and ref.endswith(target.id):
                return (
                    [
                        Evidence(
                            signal="source-asserted-patient-link",
                            detail=f"{source.key} declares Patient.link type '{link.type}' "
                            f"to {ref}. The source system asserts the relationship.",
                            strength=EvidenceStrength.DECISIVE,
                            direction=EvidenceDirection.FOR,
                        )
                    ],
                    link.type,
                )
    return (
        [
            Evidence(
                signal="no-patient-link",
                detail="Neither Patient declares a Patient.link. FHIR provides "
                "replaced-by / replaces / refer / seealso for exactly this purpose, "
                "and the source used none of them.",
                strength=EvidenceStrength.STRONG,
                direction=EvidenceDirection.AGAINST,
            )
        ],
        None,
    )


def _compare_identifiers(a: Patient, b: Patient) -> list[Evidence]:
    evidence: list[Evidence] = []
    a_by_system: dict[str, set[str]] = {}
    b_by_system: dict[str, set[str]] = {}
    for patient, target in ((a, a_by_system), (b, b_by_system)):
        for ident in patient.identifier:
            if ident.system and ident.value:
                target.setdefault(ident.system, set()).add(ident.value)

    for system in sorted(set(a_by_system) & set(b_by_system)):
        shared = a_by_system[system] & b_by_system[system]
        if shared:
            strong = system in _STRONG_IDENTIFIER_SYSTEMS
            evidence.append(
                Evidence(
                    signal="identifier-exact-match",
                    detail=f"Both records carry identifier '{sorted(shared)[0]}' in "
                    f"system {system}.",
                    strength=EvidenceStrength.DECISIVE if strong else EvidenceStrength.STRONG,
                    direction=EvidenceDirection.FOR,
                )
            )
            continue

        a_value, b_value = sorted(a_by_system[system])[0], sorted(b_by_system[system])[0]
        evidence.append(
            Evidence(
                signal="distinct-identifier-same-system",
                detail=f"'{a_value}' and '{b_value}' are different values issued by the "
                f"same assigning system ({system}). One system issuing two identifiers "
                f"is that system asserting two identities.",
                strength=EvidenceStrength.STRONG,
                direction=EvidenceDirection.AGAINST,
            )
        )
        if _shares_root(a_value, b_value):
            evidence.append(
                Evidence(
                    signal="identifier-shared-root",
                    detail=f"'{a_value}' and '{b_value}' share a common prefix. A suffix "
                    f"convention is a plausible reading, but the system defines no "
                    f"semantics for it, so this is a hypothesis rather than evidence.",
                    strength=EvidenceStrength.SUGGESTIVE_ONLY,
                    direction=EvidenceDirection.FOR,
                )
            )

    for system in sorted(_STRONG_IDENTIFIER_SYSTEMS):
        present = [p.key for p in (a, b) if system in (_systems_of(p))]
        if len(present) == 1:
            evidence.append(
                Evidence(
                    signal="no-corroborating-strong-identifier",
                    detail=f"A {system} identifier exists on {present[0]} only, so the "
                    f"one high-entropy identifier available cannot be cross-checked.",
                    strength=EvidenceStrength.BLOCKS_CONFIRMATION,
                    direction=EvidenceDirection.AGAINST,
                )
            )
    return evidence


def _systems_of(patient: Patient) -> set[str]:
    return {i.system for i in patient.identifier if i.system}


def _shares_root(a: str, b: str) -> bool:
    shorter, longer = sorted((a, b), key=len)
    return len(shorter) >= 4 and longer.startswith(shorter) and longer != shorter


def _compare_birthdates(a: Patient, b: Patient) -> list[Evidence]:
    """Compare without coercing either value to a precision it does not have.

    Two partial dates are compared as the intervals they denote. `1958-03-12`
    spans one day; `1958` spans a year. Overlapping intervals mean the values
    are *consistent*, which is a much weaker statement than *equal*.
    """
    a_date = PartialDate.parse(a.birthDate)
    b_date = PartialDate.parse(b.birthDate)

    if a_date is None or b_date is None:
        missing = a.key if a_date is None else b.key
        return [
            Evidence(
                signal="birthdate-absent",
                detail=f"{missing} has no usable birth date, so date of birth cannot "
                f"contribute to identity matching.",
                strength=EvidenceStrength.BLOCKS_CONFIRMATION,
                direction=EvidenceDirection.AGAINST,
            )
        ]

    overlaps = a_date.lower_bound < b_date.upper_bound and b_date.lower_bound < a_date.upper_bound
    if not overlaps:
        return [
            Evidence(
                signal="birthdate-contradictory",
                detail=f"'{a_date.value}' and '{b_date.value}' cannot denote the same "
                f"date at any precision.",
                strength=EvidenceStrength.STRONG,
                direction=EvidenceDirection.AGAINST,
            )
        ]

    precise = {DatePrecision.DAY, DatePrecision.INSTANT}
    if a_date.precision in precise and b_date.precision in precise:
        return [
            Evidence(
                signal="birthdate-exact-match",
                detail=f"Both records give a full birth date and they agree "
                f"('{a_date.value}').",
                strength=EvidenceStrength.MODERATE,
                direction=EvidenceDirection.FOR,
            )
        ]

    coarser = min(a_date.precision, b_date.precision, key=lambda p: list(DatePrecision).index(p))
    return [
        Evidence(
            signal="birthdate-consistent-at-reduced-precision",
            detail=f"'{a_date.value}' and '{b_date.value}' are consistent, but only at "
            f"{coarser.value} precision. Consistency is not confirmation.",
            strength=EvidenceStrength.WEAK,
            direction=EvidenceDirection.FOR,
        ),
        Evidence(
            signal="birthdate-precision-differs",
            detail=f"Precision differs ({a_date.precision.value} vs "
            f"{b_date.precision.value}); a day-level match was never established. "
            f"Year and sex alone are low-entropy signals.",
            strength=EvidenceStrength.BLOCKS_CONFIRMATION,
            direction=EvidenceDirection.AGAINST,
        ),
    ]


def _compare_names(a: Patient, b: Patient) -> list[Evidence]:
    evidence: list[Evidence] = []
    a_name = a.name[0] if a.name else None
    b_name = b.name[0] if b.name else None
    if a_name is None or b_name is None:
        return evidence

    if a_name.family and _normalise_text(a_name.family) == _normalise_text(b_name.family):
        evidence.append(
            Evidence(
                signal="family-name-match",
                detail=f"Both records give the family name '{a_name.family}'.",
                strength=EvidenceStrength.WEAK,
                direction=EvidenceDirection.FOR,
            )
        )
    elif a_name.family and b_name.family:
        evidence.append(
            Evidence(
                signal="family-name-differs",
                detail=f"'{a_name.family}' vs '{b_name.family}'.",
                strength=EvidenceStrength.STRONG,
                direction=EvidenceDirection.AGAINST,
            )
        )

    a_given = [_normalise_text(g) for g in a_name.given]
    b_given = [_normalise_text(g) for g in b_name.given]
    if a_given and b_given and a_given[0] == b_given[0]:
        evidence.append(
            Evidence(
                signal="given-name-match",
                detail=f"Both records give the first given name '{a_name.given[0]}'.",
                strength=EvidenceStrength.WEAK,
                direction=EvidenceDirection.FOR,
            )
        )
    if a_given[1:] != b_given[1:]:
        evidence.append(
            Evidence(
                signal="given-name-completeness-differs",
                detail=f"Middle name components differ ({a_name.given} vs {b_name.given}). "
                f"An absent middle initial neither confirms nor refutes.",
                strength=EvidenceStrength.NEUTRAL,
                direction=EvidenceDirection.AGAINST,
            )
        )
    return evidence


def _compare_demographics(a: Patient, b: Patient) -> list[Evidence]:
    evidence: list[Evidence] = []
    if a.gender and a.gender == b.gender:
        evidence.append(
            Evidence(
                signal="gender-match",
                detail=f"Both records give gender '{a.gender}'. A near-even split in the "
                f"population makes this very weak on its own.",
                strength=EvidenceStrength.VERY_WEAK,
                direction=EvidenceDirection.FOR,
            )
        )
    elif a.gender and b.gender:
        evidence.append(
            Evidence(
                signal="gender-differs",
                detail=f"'{a.gender}' vs '{b.gender}'.",
                strength=EvidenceStrength.MODERATE,
                direction=EvidenceDirection.AGAINST,
            )
        )

    a_addr = normalise_address(a.address[0] if a.address else None)
    b_addr = normalise_address(b.address[0] if b.address else None)
    if a_addr and a_addr == b_addr:
        evidence.append(
            Evidence(
                signal="address-match-normalised",
                detail=f"Addresses normalise to the same value ('{a_addr}').",
                strength=EvidenceStrength.MODERATE,
                direction=EvidenceDirection.FOR,
            )
        )
        family = a.name[0].family if a.name else None
        if family and b.name and b.name[0].family == family:
            evidence.append(
                Evidence(
                    signal="shared-address-relative-risk",
                    detail="A shared surname at a shared address is the classic master "
                    "patient index false positive -- two relatives in one household. "
                    "Nothing in this bundle excludes that reading.",
                    strength=EvidenceStrength.STRONG,
                    direction=EvidenceDirection.AGAINST,
                )
            )

    a_phones = {_digits(t.value) for t in a.telecom if t.system == "phone" and t.value}
    b_phones = {_digits(t.value) for t in b.telecom if t.system == "phone" and t.value}
    if a_phones and b_phones:
        if a_phones & b_phones:
            evidence.append(
                Evidence(
                    signal="telecom-match",
                    detail="The records share a telephone number.",
                    strength=EvidenceStrength.MODERATE,
                    direction=EvidenceDirection.FOR,
                )
            )
        else:
            evidence.append(
                Evidence(
                    signal="telecom-disjoint",
                    detail="No telephone number is shared. One person may hold several "
                    "numbers, so this does not refute -- but it confirms nothing.",
                    strength=EvidenceStrength.NEUTRAL,
                    direction=EvidenceDirection.AGAINST,
                )
            )
    return evidence


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value)


def _compare_completeness(a: Patient, b: Patient) -> list[Evidence]:
    def profile_count(p: Patient) -> int:
        return len(p.meta.profile) if p.meta else 0

    if profile_count(a) != profile_count(b) or len(a.extension) != len(b.extension):
        a_score = (profile_count(a), len(a.extension))
        b_score = (profile_count(b), len(b.extension))
        sparse = a if a_score < b_score else b
        return [
            Evidence(
                signal="completeness-asymmetry",
                detail=f"{sparse.key} carries no profile claim and fewer extensions, "
                f"suggesting a different source system or registration path. With no "
                f"Provenance in the bundle this cannot be adjudicated.",
                strength=EvidenceStrength.WEAK,
                direction=EvidenceDirection.AGAINST,
            )
        ]
    return []


# --------------------------------------------------------------------------
# Analysis
# --------------------------------------------------------------------------


def _has_overlap(evidence: list[Evidence]) -> bool:
    """Is there enough demographic agreement to call these a candidate pair at
    all? Below this bar the records are simply different people."""
    positives = {e.signal for e in evidence if e.direction is EvidenceDirection.FOR}
    return len(positives & {"family-name-match", "given-name-match", "address-match-normalised",
                            "birthdate-exact-match", "birthdate-consistent-at-reduced-precision",
                            "identifier-shared-root", "identifier-exact-match",
                            "source-asserted-patient-link"}) >= 3


class IdentityAnalyzer:
    """Compares Patient records and reports what the evidence supports."""

    def __init__(self, issues: IssueLog) -> None:
        self._issues = issues

    def analyse(
        self, patients: list[Patient], reference_counts: dict[str, int]
    ) -> IdentityAnalysis:
        if not patients:
            return IdentityAnalysis(None, "No Patient resources in the bundle.", (), ())

        primary, rationale = self._select_primary(patients, reference_counts)
        candidates: list[DuplicateCandidate] = []

        for i, a in enumerate(patients):
            for b in patients[i + 1 :]:
                candidate = self._compare(a, b)
                if candidate is not None:
                    candidates.append(candidate)
                    self._report(candidate)

        return IdentityAnalysis(
            primary_patient_id=primary.id,
            primary_selection_rationale=rationale,
            all_patient_ids=tuple(p.id for p in patients if p.id),
            candidates=tuple(candidates),
        )

    def _compare(self, a: Patient, b: Patient) -> DuplicateCandidate | None:
        link_evidence, link_type = _compare_links(a, b)
        evidence = [
            *link_evidence,
            *_compare_identifiers(a, b),
            *_compare_names(a, b),
            *_compare_birthdates(a, b),
            *_compare_demographics(a, b),
            *_compare_completeness(a, b),
        ]

        if link_type is None and not _has_overlap(evidence):
            return None

        if link_type is not None:
            determination = Determination.SOURCE_ASSERTED_LINK
            merge_performed = True
            action = "follow-source-assertion"
        else:
            determination = Determination.UNRECONCILED
            merge_performed = False
            action = "human-steward-review"

        return DuplicateCandidate(
            candidate_id=f"dup-{a.id}-{b.id}",
            member_ids=(a.id or "", b.id or ""),
            determination=determination,
            merge_performed=merge_performed,
            source_asserted_link=link_type,
            evidence_for=tuple(e for e in evidence if e.direction is EvidenceDirection.FOR),
            evidence_against=tuple(
                e for e in evidence if e.direction is EvidenceDirection.AGAINST
            ),
            recommended_action=action,
        )

    def _report(self, candidate: DuplicateCandidate) -> None:
        if candidate.determination is Determination.SOURCE_ASSERTED_LINK:
            return
        self._issues.add(
            IssueCode.DUPLICATE_CANDIDATE_UNRECONCILED,
            Severity.HIGH,
            f"Patient records {' and '.join(candidate.member_ids)} share demographic "
            f"details but the source asserts no link between them and no confirming "
            f"identifier is available. They have not been merged.",
            detail={"candidateId": candidate.candidate_id},
        )

    @staticmethod
    def _select_primary(
        patients: list[Patient], reference_counts: dict[str, int]
    ) -> tuple[Patient, str]:
        """Choose the snapshot subject.

        This is a *selection*, not a merge: the other records keep their own
        identity and their own data. Criteria are applied lexicographically
        rather than as a weighted score, so the reason for the choice is always
        a single stated fact rather than an arithmetic accident.
        """
        precision_rank = {
            DatePrecision.INSTANT: 3,
            DatePrecision.DAY: 3,
            DatePrecision.MONTH: 2,
            DatePrecision.YEAR: 1,
        }

        def key(item: tuple[int, Patient]) -> tuple[int, int, int, int, int]:
            position, patient = item
            birth = PartialDate.parse(patient.birthDate)
            return (
                reference_counts.get(patient.key, 0),
                precision_rank.get(birth.precision, 0) if birth else 0,
                len(_systems_of(patient)),
                1 if (patient.meta and patient.meta.profile) else 0,
                -position,  # earlier bundle position wins ties
            )

        position, winner = max(enumerate(patients), key=key)
        birth = PartialDate.parse(winner.birthDate)
        return winner, (
            f"Selected {winner.key} as the snapshot subject: "
            f"{reference_counts.get(winner.key, 0)} clinical resources reference it, "
            f"its birth date is recorded at {birth.precision.value if birth else 'no'} "
            f"precision, and it carries {len(_systems_of(winner))} identifier system(s). "
            f"This is a selection of which record to display, not a merge -- no data "
            f"from any other Patient record has been folded into it."
        )
