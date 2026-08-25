/**
 * Fixtures mirroring the real API payload for the supplied bundle.
 *
 * Deliberately hand-written rather than snapshotted: these encode what the
 * frontend must do with *uncertain* data, so each field is chosen to exercise
 * one uncertainty path.
 */

import type {
  AllergyItem,
  Coding,
  ConditionItem,
  DateValue,
  EncounterItem,
  ExcludedItem,
  MedicationItem,
  ObservationItem,
  PatientDetail,
  Provenance,
} from "@/lib/types";

export const provenance: Provenance = { resourceId: "x", admittedBy: "RULE_TEST" };

export function coding(overrides: Partial<Coding> = {}): Coding {
  return {
    system: "http://hl7.org/fhir/sid/icd-10-cm",
    code: "I10",
    display: "Essential (primary) hypertension",
    displayStatus: "from-source",
    systemName: "ICD-10-CM",
    displaySource: "fhir",
    displaySourceDetail: null,
    codeSystemMismatch: false,
    mismatchReason: null,
    usableForCodedLogic: true,
    ...overrides,
  };
}

/** A code the source never named. The UI must not invent one. */
export const undisplayedCoding = coding({
  code: "E11.9",
  display: null,
  displayStatus: "unresolved",
  displaySource: "unavailable",
});

/** A display on a code that does not validate against its declared system. */
export const mismatchedCoding = coding({
  system: "http://snomed.info/sct",
  systemName: "SNOMED CT",
  code: "7980-2",
  display: "Penicillin",
  displayStatus: "from-source-unvalidated",
  codeSystemMismatch: true,
  mismatchReason: "Code '7980-2' is not a well-formed identifier for SNOMED CT",
  usableForCodedLogic: false,
});

export const yearOnly: DateValue = { value: "2019", precision: "year" };
export const fullDate: DateValue = { value: "1958-03-12", precision: "day" };
export const instant: DateValue = { value: "2025-11-04T14:12:00Z", precision: "instant" };

export const condition = (o: Partial<ConditionItem> = {}): ConditionItem => ({
  id: "condition-001",
  code: coding(),
  clinicalStatus: coding({ display: "Active", code: "active" }),
  verificationStatus: coding({ display: "Confirmed", code: "confirmed" }),
  onset: instant,
  encounter: null,
  categoryDeclared: false,
  flags: [],
  provenance,
  ...o,
});

export const medication = (o: Partial<MedicationItem> = {}): MedicationItem => ({
  id: "medicationrequest-001",
  status: "active",
  medication: coding({ code: "197361", display: "Lisinopril 10 MG Oral Tablet" }),
  dosageText: "Take one tablet by mouth once daily",
  authoredOn: instant,
  flags: [],
  provenance,
  attribution: null,
  ...o,
});

export const allergy = (o: Partial<AllergyItem> = {}): AllergyItem => ({
  id: "allergyintolerance-001",
  code: mismatchedCoding,
  clinicalStatus: coding({ display: "Active", code: "active" }),
  verificationStatus: coding({ display: "Confirmed", code: "confirmed" }),
  criticality: "high",
  recordedDate: fullDate,
  flags: [],
  provenance,
  ...o,
});

export const observation = (o: Partial<ObservationItem> = {}): ObservationItem => ({
  id: "observation-001",
  code: coding({ code: "85354-9", display: "Blood pressure panel", systemName: "LOINC" }),
  categoryDeclared: "vital-signs",
  effective: instant,
  value: null,
  unit: null,
  components: [
    { code: coding({ display: "Systolic blood pressure" }), value: 138, unit: "mmHg" },
    { code: coding({ display: "Diastolic blood pressure" }), value: 88, unit: "mmHg" },
  ],
  performer: null,
  encounter: null,
  referenceRangeAvailable: false,
  interpretationAvailable: false,
  flags: [],
  provenance,
  ...o,
});

export const encounter = (o: Partial<EncounterItem> = {}): EncounterItem => ({
  id: "encounter-001",
  status: "finished",
  encounterClass: coding({ display: "Ambulatory", code: "AMB" }),
  type: coding({ code: "185349003", display: "Encounter for check up" }),
  periodStart: instant,
  periodEnd: null,
  flags: [],
  provenance,
  ...o,
});

export const excluded = (o: Partial<ExcludedItem> = {}): ExcludedItem => ({
  id: "observation-004",
  resourceType: "Observation",
  suppressionReason: "entered-in-error",
  suppressionField: "Observation.status",
  summary: "Creatinine [Mass/volume] in Serum or Plasma",
  valueWithheld: true,
  valueWithheldReason: "Retracted result; the numeric value is withheld from all views.",
  ...o,
});

export const patient = (o: Partial<PatientDetail> = {}): PatientDetail => ({
  id: "patient-001",
  familyName: "Whitfield",
  givenNames: ["Dorothy", "M"],
  gender: "female",
  birthDate: fullDate,
  identifiers: [
    { system: "http://centaurihealth.example.org/mrn", systemName: "MRN", value: "MRN-48213", masked: false },
  ],
  addressLines: ["482 Larkspur Lane"],
  city: "Springvale",
  state: "OH",
  postalCode: "44011",
  telecom: [["phone", "555-014-2231"]],
  profilesClaimed: ["http://hl7.org/fhir/us/core/StructureDefinition/us-core-patient"],
  usCore: {
    race: coding({ display: "White" }),
    raceText: "White",
    ethnicity: coding({ display: "Not Hispanic or Latino" }),
    ethnicityText: "Not Hispanic or Latino",
    birthsex: null,
  },
  withheldIdentifierCount: 1,
  ...o,
});
