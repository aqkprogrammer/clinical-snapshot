/**
 * Mirrors the API contract in apps/api/src/clinical_snapshot/schemas/responses.py.
 *
 * The uncertainty-bearing fields are the point of this file. `display: string | null`
 * with a `displayStatus` discriminator forces every call site to decide what to
 * render when a code has no name, rather than letting `display ?? code` slip in.
 */

export type DisplaySource = "fhir" | "verified-local-map" | "unavailable";

export type DisplayStatus =
  | "from-source"
  | "from-source-unvalidated"
  | "resolved-local"
  | "unresolved";

export type DatePrecision = "year" | "month" | "day" | "instant";

export interface DateValue {
  value: string;
  precision: DatePrecision;
}

export interface Coding {
  system: string | null;
  code: string | null;
  display: string | null;
  displayStatus: DisplayStatus;
  systemName: string | null;
  displaySource: DisplaySource;
  displaySourceDetail: string | null;
  codeSystemMismatch: boolean;
  mismatchReason: string | null;
  usableForCodedLogic: boolean;
}

export interface ReferenceValue {
  reference: string;
  resolved: boolean;
  display: string | null;
  reason: string | null;
}

export interface Provenance {
  resourceId: string;
  admittedBy: string;
}

export interface Attribution {
  patientId: string;
  patientLabel: string;
  candidateId: string;
  note: string;
}

export interface Warning {
  code: string;
  severity: "high" | "medium" | "low";
  message: string;
  detail: Record<string, string>;
}

export interface Issue {
  code: string;
  severity: "high" | "medium" | "low";
  message: string;
  resourceId: string | null;
  resourceType: string | null;
  path: string | null;
  detail: Record<string, string>;
}

export interface ConditionItem {
  id: string;
  code: Coding;
  clinicalStatus: Coding | null;
  verificationStatus: Coding | null;
  onset: DateValue | null;
  encounter: ReferenceValue | null;
  categoryDeclared: boolean;
  flags: string[];
  provenance: Provenance;
}

export interface MedicationItem {
  id: string;
  status: string | null;
  medication: Coding;
  dosageText: string | null;
  authoredOn: DateValue | null;
  flags: string[];
  provenance: Provenance;
  attribution: Attribution | null;
}

export interface AllergyItem {
  id: string;
  code: Coding;
  clinicalStatus: Coding | null;
  verificationStatus: Coding | null;
  criticality: string | null;
  recordedDate: DateValue | null;
  flags: string[];
  provenance: Provenance;
}

export interface ObservationComponent {
  code: Coding;
  value: number | null;
  unit: string | null;
}

export interface ObservationItem {
  id: string;
  code: Coding;
  categoryDeclared: string | null;
  effective: DateValue | null;
  value: number | null;
  unit: string | null;
  components: ObservationComponent[];
  performer: ReferenceValue | null;
  encounter: ReferenceValue | null;
  referenceRangeAvailable: boolean;
  interpretationAvailable: boolean;
  flags: string[];
  provenance: Provenance;
}

export interface EncounterItem {
  id: string;
  status: string | null;
  encounterClass: Coding | null;
  type: Coding | null;
  periodStart: DateValue | null;
  periodEnd: DateValue | null;
  flags: string[];
  provenance: Provenance;
}

export interface ExcludedItem {
  id: string;
  resourceType: string;
  suppressionReason: string;
  suppressionField: string | null;
  summary: string;
  valueWithheld: boolean;
  valueWithheldReason: string | null;
}

export interface NeedsReviewItem {
  id: string;
  resourceType: string;
  reasons: string[];
  summary: string;
  detail: string;
}

export interface UsCoreExtensions {
  race: Coding | null;
  raceText: string | null;
  ethnicity: Coding | null;
  ethnicityText: string | null;
  birthsex: string | null;
}

export interface PatientIdentifier {
  system: string | null;
  systemName: string | null;
  value: string | null;
  masked: boolean;
}

export interface PatientDetail {
  id: string;
  familyName: string | null;
  givenNames: string[];
  gender: string | null;
  birthDate: DateValue | null;
  identifiers: PatientIdentifier[];
  addressLines: string[];
  city: string | null;
  state: string | null;
  postalCode: string | null;
  telecom: [string, string][];
  profilesClaimed: string[];
  usCore: UsCoreExtensions;
}

export interface Evidence {
  signal: string;
  detail: string;
  strength: string;
  direction: "for" | "against";
}

export type MatchConfidence =
  | "confirmed"
  | "conflicted"
  | "probable"
  | "possible"
  | "insufficient";

export interface DuplicateCandidate {
  candidateId: string;
  memberIds: string[];
  determination: "source-asserted-link" | "unreconciled" | "distinct";
  confidence: MatchConfidence;
  canonicalPatientId: string | null;
  memberResourceIds: Record<string, string[]>;
  mergePerformed: boolean;
  sourceAssertedLink: string | null;
  evidenceFor: Evidence[];
  evidenceAgainst: Evidence[];
  recommendedAction: string;
}

export interface IdentityAnalysis {
  primaryPatientId: string | null;
  primarySelectionRationale: string;
  allPatientIds: string[];
  candidates: DuplicateCandidate[];
}

export interface SnapshotMeta {
  patientId: string;
  bundleId: string | null;
  bundleTimestamp: string | null;
  latestClinicalActivity: string | null;
  generatedAt: string;
  daysSinceBundleExport: number | null;
  daysSinceLatestActivity: number | null;
  scopeNote: string;
}

export interface SnapshotData {
  warnings: Warning[];
  patient: PatientDetail;
  conditionsCurrent: ConditionItem[];
  conditionsHistorical: ConditionItem[];
  conditionsCategoryDeclared: boolean;
  medicationsActive: MedicationItem[];
  medicationsHistorical: MedicationItem[];
  allergiesCurrent: AllergyItem[];
  allergiesHistorical: AllergyItem[];
  vitalSigns: ObservationItem[];
  otherObservations: ObservationItem[];
  encounters: EncounterItem[];
  needsReview: NeedsReviewItem[];
  identity: IdentityAnalysis;
}

export interface SnapshotResponse {
  meta: SnapshotMeta;
  data: SnapshotData;
  issues: Issue[];
}

export interface PatientSummary {
  id: string;
  display: string;
  identifiers: PatientIdentifier[];
  birthDate: DateValue | null;
  gender: string | null;
  profileClaimed: string[];
  resourceCounts: Record<string, number>;
}

export interface PatientsResponse {
  meta: Record<string, string | number | null>;
  data: { patients: PatientSummary[]; duplicateCandidates: DuplicateCandidate[] };
  issues: Issue[];
}

export interface ExcludedResponse {
  meta: Record<string, string | number | null>;
  data: { note: string; excluded: ExcludedItem[] };
}
