"""Table-driven coverage of the classification rules.

The cases that matter most are the ones where `verificationStatus` and
`clinicalStatus` disagree: the bundle's retracted Condition and
AllergyIntolerance are *also* non-active, so a rule that consults
clinicalStatus first would hide them for the wrong reason and would report the
wrong suppression mechanism to the user.
"""

import pytest
from clinical_snapshot.domain.safety import Disposition, Flag, classify
from clinical_snapshot.fhir.models import (
    AllergyIntolerance,
    CodeableConcept,
    Coding,
    Condition,
    Encounter,
    MedicationRequest,
    Observation,
    UnknownResource,
)


def concept(code: str | None) -> CodeableConcept | None:
    return None if code is None else CodeableConcept(coding=[Coding(code=code)])


class TestCondition:
    @pytest.mark.parametrize(
        ("clinical", "verification", "expected"),
        [
            ("active", "confirmed", Disposition.CURRENT),
            ("recurrence", "confirmed", Disposition.CURRENT),
            ("relapse", "confirmed", Disposition.CURRENT),
            ("inactive", "confirmed", Disposition.HISTORICAL),
            ("remission", "confirmed", Disposition.HISTORICAL),
            ("resolved", "confirmed", Disposition.HISTORICAL),
            ("active", "unconfirmed", Disposition.CURRENT),
            ("active", "provisional", Disposition.CURRENT),
            # Retraction wins over every clinicalStatus, including active.
            ("active", "entered-in-error", Disposition.EXCLUDED),
            ("inactive", "entered-in-error", Disposition.EXCLUDED),
            ("active", "refuted", Disposition.EXCLUDED),
            (None, "confirmed", Disposition.NEEDS_REVIEW),
            ("nonsense", "confirmed", Disposition.NEEDS_REVIEW),
        ],
    )
    def test_dispositions(
        self, clinical: str | None, verification: str, expected: Disposition
    ) -> None:
        result = classify(
            Condition(clinicalStatus=concept(clinical), verificationStatus=concept(verification))
        )
        assert result.disposition is expected

    def test_retraction_reports_the_verification_field_not_clinical_status(self) -> None:
        """condition-002 is inactive AND entered-in-error. The reason shown to
        the user must be the retraction, not the inactivity."""
        result = classify(
            Condition(
                clinicalStatus=concept("inactive"),
                verificationStatus=concept("entered-in-error"),
            )
        )
        assert result.disposition is Disposition.EXCLUDED
        assert result.suppression_field == "Condition.verificationStatus"
        assert "entered in error" in (result.reason or "")

    def test_unconfirmed_is_flagged_not_suppressed(self) -> None:
        result = classify(
            Condition(clinicalStatus=concept("active"), verificationStatus=concept("unconfirmed"))
        )
        assert result.disposition is Disposition.CURRENT
        assert Flag.UNCONFIRMED in result.flags


class TestAllergyIntolerance:
    @pytest.mark.parametrize(
        ("clinical", "verification", "expected"),
        [
            ("active", "confirmed", Disposition.CURRENT),
            ("active", "unconfirmed", Disposition.CURRENT),
            ("inactive", "confirmed", Disposition.HISTORICAL),
            ("resolved", "confirmed", Disposition.HISTORICAL),
            ("resolved", "entered-in-error", Disposition.EXCLUDED),
            ("active", "entered-in-error", Disposition.EXCLUDED),
            (None, "confirmed", Disposition.NEEDS_REVIEW),
        ],
    )
    def test_dispositions(
        self, clinical: str | None, verification: str, expected: Disposition
    ) -> None:
        result = classify(
            AllergyIntolerance(
                clinicalStatus=concept(clinical), verificationStatus=concept(verification)
            )
        )
        assert result.disposition is expected

    def test_unconfirmed_allergy_still_displays(self) -> None:
        """Suppressing an unconfirmed allergy risks an exposure. It displays
        with the caveat attached instead."""
        result = classify(
            AllergyIntolerance(
                clinicalStatus=concept("active"), verificationStatus=concept("unconfirmed")
            )
        )
        assert result.disposition is Disposition.CURRENT
        assert Flag.UNCONFIRMED in result.flags


class TestObservation:
    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            ("final", Disposition.CURRENT),
            ("amended", Disposition.CURRENT),
            ("corrected", Disposition.CURRENT),
            ("entered-in-error", Disposition.EXCLUDED),
            ("preliminary", Disposition.NEEDS_REVIEW),
            ("registered", Disposition.NEEDS_REVIEW),
            ("cancelled", Disposition.NEEDS_REVIEW),
            (None, Disposition.NEEDS_REVIEW),
            ("nonsense", Disposition.NEEDS_REVIEW),
        ],
    )
    def test_dispositions(self, status: str | None, expected: Disposition) -> None:
        assert classify(Observation(status=status)).disposition is expected

    def test_retraction_reports_the_status_field(self) -> None:
        result = classify(Observation(status="entered-in-error"))
        assert result.suppression_field == "Observation.status"


class TestEncounter:
    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            ("finished", Disposition.HISTORICAL),
            ("in-progress", Disposition.CURRENT),
            ("arrived", Disposition.CURRENT),
            ("entered-in-error", Disposition.EXCLUDED),
            ("cancelled", Disposition.HISTORICAL),
            ("planned", Disposition.NEEDS_REVIEW),
            (None, Disposition.NEEDS_REVIEW),
        ],
    )
    def test_dispositions(self, status: str | None, expected: Disposition) -> None:
        assert classify(Encounter(status=status)).disposition is expected

    def test_cancelled_is_flagged_so_it_never_reads_as_attended(self) -> None:
        result = classify(Encounter(status="cancelled"))
        assert Flag.CANCELLED in result.flags


class TestMedicationRequest:
    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            ("active", Disposition.CURRENT),
            ("on-hold", Disposition.CURRENT),
            ("stopped", Disposition.HISTORICAL),
            ("completed", Disposition.HISTORICAL),
            ("cancelled", Disposition.HISTORICAL),
            ("entered-in-error", Disposition.EXCLUDED),
            ("draft", Disposition.NEEDS_REVIEW),
            ("unknown", Disposition.NEEDS_REVIEW),
            (None, Disposition.NEEDS_REVIEW),
        ],
    )
    def test_dispositions(self, status: str | None, expected: Disposition) -> None:
        assert classify(MedicationRequest(status=status)).disposition is expected

    def test_stopped_is_historical_not_excluded(self) -> None:
        """A stopped medication is a real fact about the patient's history.
        Suppressing it would lose genuine clinical information."""
        result = classify(MedicationRequest(status="stopped"))
        assert result.disposition is Disposition.HISTORICAL
        assert not result.is_excluded


class TestUnsupportedTypes:
    def test_unknown_resource_type_needs_review_rather_than_being_shown(self) -> None:
        result = classify(UnknownResource(resourceType="Procedure"))
        assert result.disposition is Disposition.NEEDS_REVIEW
