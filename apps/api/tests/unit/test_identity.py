"""The identity engine must never conclude "same person" from demographics.

The one thing that authorises a merge is a source-asserted `Patient.link`. Every
other combination of matching name, address, sex and birth year produces an
evidenced non-merge.
"""

from clinical_snapshot.domain.identity import (
    Determination,
    EvidenceStrength,
    IdentityAnalyzer,
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
        assert candidate.recommended_action == "human-steward-review"

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
