"""The identity engine must never conclude "same person" from demographics.

The one thing that authorises a merge is a source-asserted `Patient.link`. Every
other combination of matching name, address, sex and birth year produces an
evidenced non-merge.
"""

from clinical_snapshot.domain.identity import (
    Determination,
    EvidenceStrength,
    IdentityAnalyzer,
    MatchConfidence,
    normalise_address,
)
from clinical_snapshot.domain.issues import IssueCode, IssueLog
from clinical_snapshot.fhir.models import (
    Address,
    ContactPoint,
    HumanName,
    Identifier,
    Meta,
    Patient,
    PatientLink,
    Reference,
)

MRN = "http://centaurihealth.example.org/mrn"
SSN = "http://hl7.org/fhir/sid/us-ssn"


def whitfield_a(**overrides: object) -> Patient:
    base: dict[str, object] = {
        "id": "patient-001",
        "identifier": [
            Identifier(system=MRN, value="MRN-48213"),
            Identifier(system=SSN, value="***-**-4471"),
        ],
        "name": [HumanName(family="Whitfield", given=["Dorothy", "M"])],
        "gender": "female",
        "birthDate": "1958-03-12",
        "address": [
            Address(
                line=["482 Larkspur Lane"], city="Springvale", state="OH", postalCode="44011"
            )
        ],
        "telecom": [ContactPoint(system="phone", value="555-014-2231", use="home")],
        "meta": Meta(profile=["http://hl7.org/fhir/us/core/StructureDefinition/us-core-patient"]),
    }
    return Patient(**{**base, **overrides})  # type: ignore[arg-type]


def whitfield_b(**overrides: object) -> Patient:
    base: dict[str, object] = {
        "id": "patient-002",
        "identifier": [Identifier(system=MRN, value="MRN-48213-A")],
        "name": [HumanName(family="Whitfield", given=["Dorothy"])],
        "gender": "female",
        "birthDate": "1958",
        "address": [
            Address(
                line=["482 Larkspur Ln"], city="Springvale", state="OH", postalCode="44011"
            )
        ],
        "telecom": [ContactPoint(system="phone", value="555-014-9987", use="mobile")],
    }
    return Patient(**{**base, **overrides})  # type: ignore[arg-type]


def analyse(*patients: Patient, counts: dict[str, int] | None = None):
    log = IssueLog()
    result = IdentityAnalyzer(log).analyse(list(patients), counts or {})
    return result, log


class TestNoMergeWithoutSourceAssertion:
    def test_overlapping_demographics_do_not_merge(self) -> None:
        result, _ = analyse(whitfield_a(), whitfield_b())
        candidate = result.candidates[0]
        assert candidate.determination is Determination.UNRECONCILED
        assert candidate.merge_performed is False
        assert candidate.recommended_action.startswith("human-steward-review")

    def test_raises_a_high_severity_issue(self) -> None:
        _, log = analyse(whitfield_a(), whitfield_b())
        assert log.with_code(IssueCode.DUPLICATE_CANDIDATE_UNRECONCILED)

    def test_records_evidence_on_both_sides(self) -> None:
        result, _ = analyse(whitfield_a(), whitfield_b())
        candidate = result.candidates[0]
        assert candidate.evidence_for and candidate.evidence_against
        signals_for = {e.signal for e in candidate.evidence_for}
        signals_against = {e.signal for e in candidate.evidence_against}
        assert "address-match-normalised" in signals_for
        assert "family-name-match" in signals_for
        assert "no-patient-link" in signals_against
        assert "distinct-identifier-same-system" in signals_against
        assert "shared-address-relative-risk" in signals_against

    def test_distinct_mrns_in_one_system_argue_against(self) -> None:
        result, _ = analyse(whitfield_a(), whitfield_b())
        evidence = next(
            e
            for e in result.candidates[0].evidence_against
            if e.signal == "distinct-identifier-same-system"
        )
        assert evidence.strength is EvidenceStrength.STRONG

    def test_shared_mrn_root_is_suggestive_only_never_decisive(self) -> None:
        result, _ = analyse(whitfield_a(), whitfield_b())
        evidence = next(
            e for e in result.candidates[0].evidence_for if e.signal == "identifier-shared-root"
        )
        assert evidence.strength is EvidenceStrength.SUGGESTIVE_ONLY

    def test_year_only_birthdate_never_yields_an_exact_match(self) -> None:
        result, _ = analyse(whitfield_a(), whitfield_b())
        signals = {e.signal for e in result.candidates[0].evidence_for}
        assert "birthdate-exact-match" not in signals
        assert "birthdate-consistent-at-reduced-precision" in signals


class TestSourceAssertedLink:
    def test_patient_link_authorises_reconciliation(self) -> None:
        linked = whitfield_a(
            link=[PatientLink(other=Reference(reference="Patient/patient-002"), type="replaces")]
        )
        result, log = analyse(linked, whitfield_b())
        candidate = result.candidates[0]
        assert candidate.determination is Determination.SOURCE_ASSERTED_LINK
        assert candidate.merge_performed is True
        assert candidate.source_asserted_link == "replaces"
        # A followed source assertion is not a data-quality problem.
        assert not log.with_code(IssueCode.DUPLICATE_CANDIDATE_UNRECONCILED)

    def test_link_is_detected_in_either_direction(self) -> None:
        linked_b = whitfield_b(
            link=[PatientLink(other=Reference(reference="Patient/patient-001"), type="replaced-by")]
        )
        result, _ = analyse(whitfield_a(), linked_b)
        assert result.candidates[0].determination is Determination.SOURCE_ASSERTED_LINK


class TestStrongIdentifiers:
    def test_matching_ssn_is_decisive_evidence_for(self) -> None:
        b = whitfield_b(
            identifier=[
                Identifier(system=MRN, value="MRN-99999"),
                Identifier(system=SSN, value="***-**-4471"),
            ]
        )
        result, _ = analyse(whitfield_a(), b)
        match = next(
            e for e in result.candidates[0].evidence_for if e.signal == "identifier-exact-match"
        )
        assert match.strength is EvidenceStrength.DECISIVE

    def test_matching_ssn_alone_still_does_not_merge(self) -> None:
        """Even decisive evidence does not authorise the application to merge.
        Only the source system may assert identity."""
        b = whitfield_b(
            identifier=[
                Identifier(system=MRN, value="MRN-99999"),
                Identifier(system=SSN, value="***-**-4471"),
            ]
        )
        result, _ = analyse(whitfield_a(), b)
        assert result.candidates[0].merge_performed is False

    def test_missing_ssn_on_one_side_blocks_confirmation(self) -> None:
        result, _ = analyse(whitfield_a(), whitfield_b())
        evidence = next(
            e
            for e in result.candidates[0].evidence_against
            if e.signal == "no-corroborating-strong-identifier"
        )
        assert evidence.strength is EvidenceStrength.BLOCKS_CONFIRMATION


class TestDistinctPeople:
    def test_contradictory_birthdates_argue_strongly_against(self) -> None:
        result, _ = analyse(whitfield_a(), whitfield_b(birthDate="1972"))
        candidate = result.candidates[0]
        if candidate is not None:
            signals = {e.signal for e in candidate.evidence_against}
            assert "birthdate-contradictory" in signals

    def test_unrelated_patients_produce_no_candidate(self) -> None:
        other = Patient(
            id="patient-003",
            identifier=[Identifier(system=MRN, value="MRN-70001")],
            name=[HumanName(family="Okonkwo", given=["Adaeze"])],
            gender="female",
            birthDate="1991-07-02",
            address=[
                Address(
                    line=["9 Cedar Court"], city="Fairhaven", state="OH", postalCode="44100"
                )
            ],
        )
        result, _ = analyse(whitfield_a(), other)
        assert result.candidates == ()


class TestPrimarySelection:
    def test_prefers_the_record_most_clinical_data_hangs_off(self) -> None:
        result, _ = analyse(
            whitfield_a(),
            whitfield_b(),
            counts={"Patient/patient-001": 14, "Patient/patient-002": 1},
        )
        assert result.primary_patient_id == "patient-001"

    def test_rationale_states_it_is_not_a_merge(self) -> None:
        result, _ = analyse(
            whitfield_a(), whitfield_b(), counts={"Patient/patient-001": 14}
        )
        assert "not a merge" in result.primary_selection_rationale

    def test_falls_back_to_birthdate_precision_when_reference_counts_tie(self) -> None:
        result, _ = analyse(whitfield_b(), whitfield_a(), counts={})
        assert result.primary_patient_id == "patient-001"


class TestAddressNormalisation:
    def test_expands_common_street_suffixes(self) -> None:
        a = Address(line=["482 Larkspur Lane"], city="Springvale", state="OH", postalCode="44011")
        b = Address(line=["482 Larkspur Ln"], city="Springvale", state="OH", postalCode="44011")
        assert normalise_address(a) == normalise_address(b)

    def test_does_not_collapse_genuinely_different_addresses(self) -> None:
        a = Address(line=["482 Larkspur Lane"], city="Springvale")
        b = Address(line=["484 Larkspur Lane"], city="Springvale")
        assert normalise_address(a) != normalise_address(b)

    def test_absent_address_normalises_to_empty_and_never_matches(self) -> None:
        assert normalise_address(None) == ""


class TestReconciliationScenarios:
    """The eight situations the reconciliation policy has to get right.

    The through-line: no combination of demographic agreement produces a merge,
    and conflicting strong identifiers outrank demographic agreement entirely.
    """

    # 1 --------------------------------------------------------------------
    def test_exact_demographic_match_is_still_not_a_merge(self) -> None:
        """Identical name, sex, DOB and address, different MRNs. This is the
        shape of two relatives in one household, and of one person registered
        twice. The data cannot tell them apart, so neither does the app."""
        twin = whitfield_b(
            birthDate="1958-03-12",
            name=[HumanName(family="Whitfield", given=["Dorothy", "M"])],
        )
        result, log = analyse(whitfield_a(), twin)
        candidate = result.candidates[0]
        assert candidate.merge_performed is False
        assert candidate.confidence is MatchConfidence.CONFLICTED
        assert log.with_code(IssueCode.DUPLICATE_CANDIDATE_UNRECONCILED)

    # 2 --------------------------------------------------------------------
    def test_partial_date_compatibility_is_consistency_not_equality(self) -> None:
        result, _ = analyse(whitfield_a(), whitfield_b())
        signals = {e.signal for e in result.candidates[0].evidence_for}
        assert "birthdate-consistent-at-reduced-precision" in signals
        assert "birthdate-exact-match" not in signals
        blockers = {
            e.signal
            for e in result.candidates[0].evidence_against
            if e.strength is EvidenceStrength.BLOCKS_CONFIRMATION
        }
        assert "birthdate-precision-differs" in blockers

    def test_incompatible_birth_years_are_evidence_against(self) -> None:
        result, _ = analyse(whitfield_a(), whitfield_b(birthDate="1972"))
        candidate = result.candidates[0]
        assert "birthdate-contradictory" in {e.signal for e in candidate.evidence_against}
        assert candidate.confidence is MatchConfidence.CONFLICTED

    # 3 --------------------------------------------------------------------
    def test_conflicting_mrn_outranks_every_demographic_signal(self) -> None:
        """The safety principle, stated as a test: perfect demographics plus a
        strong-identifier conflict must not yield a confident match."""
        twin = whitfield_b(
            birthDate="1958-03-12",
            name=[HumanName(family="Whitfield", given=["Dorothy", "M"])],
            telecom=[ContactPoint(system="phone", value="555-014-2231", use="home")],
        )
        result, _ = analyse(whitfield_a(), twin)
        candidate = result.candidates[0]
        assert candidate.confidence is MatchConfidence.CONFLICTED
        assert candidate.merge_performed is False
        assert candidate.recommended_action == "human-steward-review-identifier-conflict"

    # 4 --------------------------------------------------------------------
    def test_conflicting_phone_is_recorded_but_does_not_refute(self) -> None:
        """One person may hold several numbers, so disjoint telecom confirms
        nothing -- it must not be scored as though it refuted."""
        result, _ = analyse(whitfield_a(), whitfield_b())
        telecom = next(
            e for e in result.candidates[0].evidence_against if e.signal == "telecom-disjoint"
        )
        assert telecom.strength is EvidenceStrength.NEUTRAL

    def test_shared_phone_is_positive_evidence(self) -> None:
        sharing = whitfield_b(
            telecom=[ContactPoint(system="phone", value="(555) 014-2231", use="home")]
        )
        result, _ = analyse(whitfield_a(), sharing)
        assert "telecom-match" in {e.signal for e in result.candidates[0].evidence_for}

    # 5 --------------------------------------------------------------------
    def test_same_address_different_identifiers_raises_the_relative_risk(self) -> None:
        result, _ = analyse(whitfield_a(), whitfield_b())
        candidate = result.candidates[0]
        risk = next(
            e for e in candidate.evidence_against if e.signal == "shared-address-relative-risk"
        )
        assert risk.strength is EvidenceStrength.STRONG
        assert "household" in risk.detail

    # 6 --------------------------------------------------------------------
    def test_incomplete_demographics_block_confirmation_rather_than_matching(self) -> None:
        sparse = Patient(
            id="patient-004",
            identifier=[Identifier(system=MRN, value="MRN-48213-B")],
            name=[HumanName(family="Whitfield")],
        )
        result, _ = analyse(whitfield_a(), sparse)
        if result.candidates:
            candidate = result.candidates[0]
            assert candidate.merge_performed is False
            assert candidate.confidence is not MatchConfidence.PROBABLE

    def test_missing_birthdate_is_reported_as_blocking(self) -> None:
        no_dob = whitfield_b(birthDate=None)
        result, _ = analyse(whitfield_a(), no_dob)
        assert "birthdate-absent" in {e.signal for e in result.candidates[0].evidence_against}

    def test_a_patient_with_almost_no_data_is_not_matched_to_anyone(self) -> None:
        bare = Patient(id="patient-005")
        result, _ = analyse(whitfield_a(), bare)
        assert result.candidates == ()

    # 7 --------------------------------------------------------------------
    def test_unrelated_patients_produce_no_candidate_at_all(self) -> None:
        other = Patient(
            id="patient-003",
            identifier=[Identifier(system=MRN, value="MRN-70001")],
            name=[HumanName(family="Okonkwo", given=["Adaeze"])],
            gender="female",
            birthDate="1991-07-02",
            address=[
                Address(
                    line=["9 Cedar Court"], city="Fairhaven", state="OH", postalCode="44100"
                )
            ],
        )
        result, log = analyse(whitfield_a(), other)
        assert result.candidates == ()
        assert not log.with_code(IssueCode.DUPLICATE_CANDIDATE_UNRECONCILED)

    def test_a_single_patient_produces_no_candidates(self) -> None:
        result, _ = analyse(whitfield_a())
        assert result.candidates == ()
        assert result.primary_patient_id == "patient-001"

    # 8 --------------------------------------------------------------------
    def test_multiple_plausible_candidates_are_all_surfaced(self) -> None:
        """Three overlapping records yield three pairwise candidates, not one
        merged cluster. Clustering would assert a transitive identity claim the
        evidence does not support."""
        third = whitfield_b(
            id="patient-003", identifier=[Identifier(system=MRN, value="MRN-48213-C")]
        )
        result, log = analyse(whitfield_a(), whitfield_b(), third)
        pairs = {tuple(sorted(c.member_ids)) for c in result.candidates}
        assert pairs == {
            ("patient-001", "patient-002"),
            ("patient-001", "patient-003"),
            ("patient-002", "patient-003"),
        }
        assert all(not c.merge_performed for c in result.candidates)
        assert len(log.with_code(IssueCode.DUPLICATE_CANDIDATE_UNRECONCILED)) == 3

    def test_no_patient_resource_is_discarded(self) -> None:
        third = whitfield_b(
            id="patient-003", identifier=[Identifier(system=MRN, value="MRN-48213-C")]
        )
        result, _ = analyse(whitfield_a(), whitfield_b(), third)
        assert set(result.all_patient_ids) == {"patient-001", "patient-002", "patient-003"}

    def test_exactly_one_canonical_candidate_is_chosen_and_it_is_a_real_record(self) -> None:
        third = whitfield_b(
            id="patient-003", identifier=[Identifier(system=MRN, value="MRN-48213-C")]
        )
        result, _ = analyse(
            whitfield_a(), whitfield_b(), third, counts={"Patient/patient-001": 14}
        )
        assert result.primary_patient_id in result.all_patient_ids
        assert all(c.canonical_patient_id == result.primary_patient_id for c in result.candidates)


class TestConfidenceGrading:
    def test_source_link_is_the_only_confirmed_state(self) -> None:
        linked = whitfield_a(
            link=[PatientLink(other=Reference(reference="Patient/patient-002"), type="replaces")]
        )
        result, _ = analyse(linked, whitfield_b())
        assert result.candidates[0].confidence is MatchConfidence.CONFIRMED

    def test_matching_strong_identifier_without_conflict_is_probable(self) -> None:
        b = whitfield_b(identifier=[Identifier(system=SSN, value="***-**-4471")])
        result, _ = analyse(whitfield_a(), b)
        assert result.candidates[0].confidence is MatchConfidence.PROBABLE
        assert result.candidates[0].merge_performed is False

    def test_matching_ssn_alongside_conflicting_mrn_is_conflicted(self) -> None:
        b = whitfield_b(
            identifier=[
                Identifier(system=MRN, value="MRN-48213-A"),
                Identifier(system=SSN, value="***-**-4471"),
            ]
        )
        result, _ = analyse(whitfield_a(), b)
        assert result.candidates[0].confidence is MatchConfidence.CONFLICTED

    def test_grading_is_deterministic(self) -> None:
        grades = {
            analyse(whitfield_a(), whitfield_b())[0].candidates[0].confidence
            for _ in range(20)
        }
        assert grades == {MatchConfidence.CONFLICTED}
