"""Terminology resolution: the refusal to invent, and code-shape validation."""

from clinical_snapshot.domain.issues import IssueCode, IssueLog
from clinical_snapshot.domain.terminology import DisplayStatus, TerminologyService

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
