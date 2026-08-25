"""Terminology resolution: the refusal to invent, and code-shape validation."""

from clinical_snapshot.domain.issues import IssueCode, IssueLog
from clinical_snapshot.domain.terminology import (
    DisplaySource,
    DisplayStatus,
    TerminologyService,
)
from clinical_snapshot.fhir.models import CodeableConcept, Coding

SNOMED = "http://snomed.info/sct"
LOINC = "http://loinc.org"
RXNORM = "http://www.nlm.nih.gov/research/umls/rxnorm"
ICD10 = "http://hl7.org/fhir/sid/icd-10-cm"
VER_STATUS = "http://terminology.hl7.org/CodeSystem/condition-ver-status"


def service() -> tuple[TerminologyService, IssueLog]:
    log = IssueLog()
    return TerminologyService(log), log


class TestNeverInvents:
    def test_missing_display_stays_missing(self) -> None:
        svc, log = service()
        missing = [(ICD10, "E11.9"), (LOINC, "4548-4"), (RXNORM, "849574"), (SNOMED, "91936005")]
        for system, code in missing:
            result = svc.resolve(system, code, None)
            assert result.display is None
            assert result.display_status is DisplayStatus.UNRESOLVED
        assert len(log.with_code(IssueCode.TERMINOLOGY_DISPLAY_MISSING)) == 4

    def test_source_display_is_passed_through_unchanged(self) -> None:
        svc, _ = service()
        result = svc.resolve(ICD10, "I10", "Essential (primary) hypertension")
        assert result.display == "Essential (primary) hypertension"
        assert result.display_status is DisplayStatus.FROM_SOURCE

    def test_fhir_codesystem_displays_resolve_from_the_curated_map(self) -> None:
        svc, _ = service()
        result = svc.resolve(VER_STATUS, "confirmed", None)
        assert result.display == "Confirmed"
        assert result.display_status is DisplayStatus.RESOLVED_LOCAL
        assert result.display_source


class TestCodeShapeValidation:
    def test_loinc_shaped_code_declared_as_snomed_is_rejected(self) -> None:
        svc, log = service()
        result = svc.resolve(SNOMED, "7980-2", "Penicillin")
        assert result.code_system_mismatch is True
        assert result.usable_for_coded_logic is False
        assert result.display == "Penicillin"
        assert result.display_status is DisplayStatus.FROM_SOURCE_UNVALIDATED
        assert log.with_code(IssueCode.CODE_SYSTEM_MISMATCH)

    def test_well_formed_codes_pass(self) -> None:
        svc, log = service()
        valid = [(SNOMED, "91936005"), (LOINC, "4548-4"), (RXNORM, "849574"), (ICD10, "E11.9")]
        for system, code in valid:
            assert svc.resolve(system, code, None).usable_for_coded_logic is True
        assert not log.with_code(IssueCode.CODE_SYSTEM_MISMATCH)

    def test_systems_without_a_shape_rule_are_not_rejected(self) -> None:
        svc, _ = service()
        result = svc.resolve("http://example.org/local-codes", "ANYTHING-GOES", "Local concept")
        assert result.code_system_mismatch is False


class TestSystemNames:
    def test_known_systems_get_their_published_name(self) -> None:
        svc, _ = service()
        assert svc.system_name(ICD10) == "ICD-10-CM"
        assert svc.system_name(SNOMED) == "SNOMED CT"

    def test_unknown_system_is_shortened_not_interpreted(self) -> None:
        svc, _ = service()
        assert svc.system_name("http://centaurihealth.example.org/mrn") == "MRN"
        assert svc.system_name("http://example.org/identifiers/encounter") == "encounter"


class TestDisplaySource:
    def test_source_display_is_attributed_to_fhir(self) -> None:
        svc, _ = service()
        result = svc.resolve(ICD10, "I10", "Essential (primary) hypertension")
        assert result.display_source is DisplaySource.FHIR

    def test_curated_display_is_attributed_to_the_local_map_and_cites_it(self) -> None:
        svc, _ = service()
        result = svc.resolve(VER_STATUS, "confirmed", None)
        assert result.display_source is DisplaySource.VERIFIED_LOCAL_MAP
        assert "condition-ver-status" in (result.display_source_detail or "")

    def test_missing_display_is_attributed_to_nothing(self) -> None:
        svc, _ = service()
        result = svc.resolve(LOINC, "4548-4", None)
        assert result.display_source is DisplaySource.UNAVAILABLE
        assert result.display_source_detail is None

    def test_unvalidated_display_still_came_from_fhir(self) -> None:
        """The display is the source's; only the code fails validation."""
        svc, _ = service()
        result = svc.resolve(SNOMED, "7980-2", "Penicillin")
        assert result.display_source is DisplaySource.FHIR
        assert result.display_status is DisplayStatus.FROM_SOURCE_UNVALIDATED


class TestPartialCodings:
    def test_missing_code_keeps_system_and_display(self) -> None:
        svc, _ = service()
        result = svc.resolve(LOINC, None, "Body weight")
        assert result.code is None
        assert result.system == LOINC
        assert result.display == "Body weight"
        assert result.display_source is DisplaySource.FHIR

    def test_missing_code_without_display_is_unavailable(self) -> None:
        svc, _ = service()
        result = svc.resolve(LOINC, None, None)
        assert result.display is None
        assert result.display_status is DisplayStatus.UNRESOLVED

    def test_missing_system_preserves_the_code(self) -> None:
        svc, _ = service()
        result = svc.resolve(None, "12345", None)
        assert result.code == "12345"
        assert result.system is None
        assert result.display is None

    def test_missing_system_cannot_be_shape_validated(self) -> None:
        svc, log = service()
        result = svc.resolve(None, "7980-2", "Penicillin")
        assert result.code_system_mismatch is False
        assert result.usable_for_coded_logic is True
        assert not log.with_code(IssueCode.CODE_SYSTEM_MISMATCH)

    def test_wholly_empty_coding_raises_no_missing_display_issue(self) -> None:
        """Nothing was recorded, so there is no display to be missing."""
        svc, log = service()
        result = svc.resolve(None, None, None)
        assert result.display is None
        assert not log.with_code(IssueCode.TERMINOLOGY_DISPLAY_MISSING)


class TestMultipleCodings:
    def test_first_coding_is_primary_and_the_rest_are_retained(self) -> None:
        svc, _ = service()
        concept = CodeableConcept(
            coding=[
                Coding(system=ICD10, code="E11.9"),
                Coding(system=SNOMED, code="44054006", display="Type 2 diabetes mellitus"),
            ]
        )
        resolved = svc.resolve_concept(concept)
        assert resolved.primary.code == "E11.9"
        assert resolved.has_alternates
        assert [a.code for a in resolved.alternates] == ["44054006"]

    def test_an_alternate_display_is_never_promoted_onto_the_primary(self) -> None:
        """The SNOMED translation has a display; the rendered ICD-10 coding does
        not. Borrowing it across systems would be inventing a label."""
        svc, _ = service()
        concept = CodeableConcept(
            coding=[
                Coding(system=ICD10, code="E11.9"),
                Coding(system=SNOMED, code="44054006", display="Type 2 diabetes mellitus"),
            ]
        )
        resolved = svc.resolve_concept(concept)
        assert resolved.primary.display is None
        assert resolved.primary.display_status is DisplayStatus.UNRESOLVED

    def test_single_coding_has_no_alternates(self) -> None:
        svc, _ = service()
        resolved = svc.resolve_concept(CodeableConcept(coding=[Coding(system=ICD10, code="I10")]))
        assert resolved.has_alternates is False

    def test_concept_with_no_codings_falls_back_to_its_own_text(self) -> None:
        svc, _ = service()
        resolved = svc.resolve_concept(CodeableConcept(text="Patient-reported wheeze"))
        assert resolved.primary.display == "Patient-reported wheeze"
        assert resolved.text == "Patient-reported wheeze"

    def test_none_concept_is_handled(self) -> None:
        svc, _ = service()
        resolved = svc.resolve_concept(None)
        assert resolved.primary.display is None
        assert resolved.has_alternates is False
