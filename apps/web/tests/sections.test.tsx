/**
 * Section components.
 *
 * The assertions are mostly about *separation*: active from historical,
 * subject's own data from an unreconciled duplicate's, clinical facts from
 * retracted ones. Mixing any of those is the failure mode that matters.
 */

import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AllergyList } from "@/components/AllergyList";
import { Banners } from "@/components/Banners";
import { ConditionList } from "@/components/ConditionList";
import { DataQualityPanel } from "@/components/DataQualityPanel";
import { DuplicateEvidence } from "@/components/DuplicateEvidence";
import { EncounterList } from "@/components/EncounterList";
import { ExcludedDrawer } from "@/components/ExcludedDrawer";
import { MedicationList } from "@/components/MedicationList";
import { ObservationList } from "@/components/ObservationList";
import { OtherResults } from "@/components/OtherResults";
import { GlanceStrip } from "@/components/GlanceStrip";
import { PatientHeader } from "@/components/PatientHeader";
import type { DuplicateCandidate, SnapshotMeta } from "@/lib/types";
import {
  allergy,
  coding,
  condition,
  encounter,
  excluded,
  medication,
  observation,
  patient,
  undisplayedCoding,
  yearOnly,
} from "./fixtures";

const meta: SnapshotMeta = {
  patientId: "patient-001",
  bundleId: "scenario1-synthetic-bundle",
  bundleTimestamp: "2026-06-01T09:00:00Z",
  latestClinicalActivity: "2025-11-04T15:00:00Z",
  generatedAt: "2026-08-25T00:00:00Z",
  daysSinceBundleExport: 85,
  daysSinceLatestActivity: 293,
  scopeNote: "Scoped to Patient/patient-001. No Patient records were merged.",
};

describe("PatientHeader", () => {
  it("renders the patient's name and MRN", () => {
    render(<PatientHeader patient={patient()} meta={meta} />);
    expect(screen.getByRole("heading", { name: "Dorothy M Whitfield" })).toBeInTheDocument();
    expect(screen.getByText("MRN-48213")).toBeInTheDocument();
  });

  it("shows that an identifier was withheld rather than looking like absent data", () => {
    render(<PatientHeader patient={patient()} meta={meta} />);
    expect(screen.getByText("1 identifier withheld")).toBeInTheDocument();
  });

  it("never renders a national identifier", () => {
    const { container } = render(<PatientHeader patient={patient()} meta={meta} />);
    expect(container.textContent).not.toContain("4471");
    expect(container.textContent).not.toContain("SSN");
  });

  it("still reports a missing US Core birthsex", () => {
    render(<PatientHeader patient={patient()} meta={meta} />);
    const facts = screen.getByText("Birth sex (US Core)").parentElement;
    expect(facts?.textContent).toContain("not recorded");
  });

  it("labels the three dates distinctly so they cannot be confused", () => {
    const { container } = render(<PatientHeader patient={patient()} meta={meta} />);
    expect(container.textContent).toContain("Record exported");
    expect(container.textContent).toContain("01 Jun 2026");
    expect(container.textContent).toContain("Last clinical activity");
    expect(container.textContent).toContain("04 Nov 2025");
    expect(container.textContent).toContain("293 days ago");
    expect(container.textContent).toContain("Page rendered");
  });

  it("shows a derived age for a day-precision birth date", () => {
    const { container } = render(<PatientHeader patient={patient()} meta={meta} />);
    expect(container.textContent).toMatch(/\d+y/);
  });

  it("shows no age when the birth date is year-only", () => {
    const { container } = render(
      <PatientHeader
        patient={patient({ birthDate: { value: "1958", precision: "year" } })}
        meta={meta}
      />,
    );
    expect(container.textContent).not.toMatch(/\b\d+y\b/);
    expect(container.textContent).toContain("(year only)");
  });

  it("leads with identity: name, sex, DOB and MRN", () => {
    const { container } = render(<PatientHeader patient={patient()} meta={meta} />);
    const idLine = container.querySelector(".id-facts");
    expect(idLine?.textContent).toContain("female");
    expect(idLine?.textContent).toContain("12 Mar 1958");
    expect(idLine?.textContent).toContain("MRN-48213");
  });

  it("folds demographics away without removing them", () => {
    const { container } = render(<PatientHeader patient={patient()} meta={meta} />);
    const details = Array.from(container.querySelectorAll("details")).find((d) =>
      d.textContent?.includes("Ethnicity"),
    );
    expect(details).toBeDefined();
    expect(details?.hasAttribute("open")).toBe(false);
    expect(details?.textContent).toContain("Not Hispanic or Latino");
    expect(details?.textContent).toContain("482 Larkspur Lane");
  });

  it("flags a record that makes no profile claim", () => {
    render(<PatientHeader patient={patient({ profilesClaimed: [] })} meta={meta} />);
    expect(screen.getByText("no profile claim")).toBeInTheDocument();
  });
});

describe("Banners", () => {
  const duplicateWarning = {
    code: "DUPLICATE_CANDIDATE_UNRECONCILED",
    severity: "high" as const,
    message:
      "A possible duplicate Patient record (patient-002) shares this patient's name, sex, " +
      "address and birth year. The source system asserts no link between them.",
    detail: {},
  };

  it("renders the unreconciled-duplicate warning prominently", () => {
    render(<Banners warnings={[duplicateWarning]} />);
    expect(screen.getByText("Possible duplicate record")).toBeInTheDocument();
  });

  it("uses a record number a clinician recognises, not a database id", () => {
    const { container } = render(
      <Banners
        warnings={[duplicateWarning]}
        duplicate={{ label: "MRN-48213-A", medicationCount: 1 }}
      />,
    );
    // Scoped to what is visible while the disclosure is collapsed.
    const headline = container.querySelector(".banner-summary");
    expect(headline?.textContent).toContain("MRN-48213-A");
    expect(headline?.textContent).not.toContain("patient-002");
  });

  it("keeps the actionable fact in the headline", () => {
    const { container } = render(
      <Banners
        warnings={[duplicateWarning]}
        duplicate={{ label: "MRN-48213-A", medicationCount: 1 }}
      />,
    );
    const headline = container.querySelector(".banner-summary");
    expect(headline?.textContent).toContain("1 active medication");
    expect(headline?.textContent).toContain("not merged");
  });

  it("folds the reasoning away but does not delete it", () => {
    const { container } = render(<Banners warnings={[duplicateWarning]} />);
    const why = container.querySelector("details");
    expect(why?.hasAttribute("open")).toBe(false);
    expect(why?.textContent).toContain("asserts no link");
  });

  it("uses a polite role rather than an assertive alert", () => {
    const { container } = render(<Banners warnings={[duplicateWarning]} />);
    expect(container.querySelector('[role="status"]')).not.toBeNull();
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });

  it("renders nothing when there are no warnings", () => {
    const { container } = render(<Banners warnings={[]} />);
    expect(container.firstChild).toBeNull();
  });
});

describe("ConditionList", () => {
  it("keeps the not-a-problem-list caveat visible as a label", () => {
    const { container } = render(
      <ConditionList current={[condition()]} historical={[]} categoryDeclared={false} />,
    );
    expect(screen.getByText("not a formal problem list")).toBeInTheDocument();
    expect(container.textContent).toContain("Condition.category");
  });

  it("omits the caveat entirely when the source did declare a category", () => {
    render(<ConditionList current={[condition()]} historical={[]} categoryDeclared />);
    expect(screen.queryByText("not a formal problem list")).toBeNull();
  });

  it("renders a condition with no display without inventing one", () => {
    const { container } = render(
      <ConditionList
        current={[condition({ id: "condition-003", code: undisplayedCoding, onset: yearOnly })]}
        historical={[]}
        categoryDeclared={false}
      />,
    );
    expect(container.textContent).toContain("ICD-10-CM E11.9 — display unavailable");
    expect(container.textContent).toContain("(year only)");
  });

  it("separates resolved conditions under their own heading", () => {
    render(
      <ConditionList
        current={[condition()]}
        historical={[condition({ id: "condition-009" })]}
        categoryDeclared={false}
      />,
    );
    expect(screen.getByText("Resolved / inactive")).toBeInTheDocument();
  });

  it("shows an empty state when there are no active conditions", () => {
    render(<ConditionList current={[]} historical={[]} categoryDeclared={false} />);
    expect(screen.getByText("No active conditions recorded.")).toBeInTheDocument();
  });
});

describe("MedicationList", () => {
  it("labels the three groups so they cannot be confused", () => {
    const { container } = render(
      <MedicationList
        active={[
          medication(),
          medication({
            id: "m3",
            attribution: {
              patientId: "patient-002",
              patientLabel: "MRN-48213-A",
              candidateId: "d",
              note: "NOT confirmed.",
            },
          }),
        ]}
        historical={[medication({ id: "m2", status: "stopped" })]}
      />,
    );
    expect(screen.getByText("Current")).toBeInTheDocument();
    expect(screen.getByText(/From possible duplicate/)).toBeInTheDocument();
    expect(screen.getByText("Stopped")).toBeInTheDocument();
    expect(container.textContent).toContain("not current — do not treat as active");
  });

  it("keeps a stopped medication out of the active list", () => {
    render(
      <MedicationList
        active={[medication()]}
        historical={[
          medication({
            id: "medicationrequest-002",
            status: "stopped",
            medication: coding({ code: "310965", display: "Metformin 500 MG Oral Tablet" }),
          }),
        ]}
      />,
    );
    expect(screen.getByText("Stopped")).toBeInTheDocument();
  });

  it("attributes a duplicate record's medication instead of absorbing it", () => {
    const { container } = render(
      <MedicationList
        active={[
          medication(),
          medication({
            id: "medicationrequest-003",
            medication: undisplayedCoding,
            attribution: {
              patientId: "patient-002",
              patientLabel: "MRN-48213-A",
              candidateId: "dup-1",
              note: "Same-person status is NOT confirmed.",
            },
          }),
        ]}
        historical={[]}
      />,
    );
    expect(container.textContent).toContain("MRN-48213-A");
    expect(container.textContent).toContain("NOT confirmed");
  });

  it("does not attribute the subject's own medications", () => {
    const { container } = render(<MedicationList active={[medication()]} historical={[]} />);
    expect(container.querySelector(".attributed")).toBeNull();
  });

  it("shows an empty state for no active medications", () => {
    render(<MedicationList active={[]} historical={[]} />);
    expect(screen.getByText("No active medications recorded.")).toBeInTheDocument();
  });

  it("marks a missing dosage rather than leaving it blank", () => {
    render(<MedicationList active={[medication({ dosageText: null })]} historical={[]} />);
    expect(screen.getByText("no dosage recorded")).toBeInTheDocument();
  });
});

describe("AllergyList", () => {
  it("shows high criticality prominently", () => {
    render(<AllergyList current={[allergy()]} historical={[]} />);
    expect(screen.getByText("high risk")).toBeInTheDocument();
  });

  it("marks an unconfirmed allergy as uncertain but still shows it", () => {
    const { container } = render(
      <AllergyList
        current={[
          allergy({
            id: "allergyintolerance-003",
            code: coding({
              system: "http://snomed.info/sct",
              systemName: "SNOMED CT",
              code: "91936005",
              display: null,
              displayStatus: "unresolved",
              displaySource: "unavailable",
            }),
            criticality: "unable-to-assess",
            flags: ["unconfirmed"],
          }),
        ]}
        historical={[]}
      />,
    );
    expect(screen.getByText("unconfirmed")).toBeInTheDocument();
    expect(container.textContent).toContain("SNOMED CT 91936005 — display unavailable");
  });

  it("shows the mismatch reason as visible text on the row", () => {
    const { container } = render(<AllergyList current={[allergy()]} historical={[]} />);
    expect(container.querySelector(".code-caveat")).not.toBeNull();
    expect(container.textContent).toContain("not a well-formed identifier for SNOMED CT");
  });

  it("states that entries are not de-duplicated when a code fails validation", () => {
    render(<AllergyList current={[allergy()]} historical={[]} />);
    expect(screen.getByText("entries not de-duplicated")).toBeInTheDocument();
  });

  it("puts severity and verification beside the substance name", () => {
    const { container } = render(<AllergyList current={[allergy()]} historical={[]} />);
    const head = container.querySelector(".row-head");
    expect(head?.textContent).toContain("Penicillin");
    expect(head?.textContent).toContain("high risk");
    expect(head?.textContent).toContain("confirmed");
  });

  it("does not equate an empty list with no known allergies", () => {
    render(<AllergyList current={[]} historical={[]} />);
    expect(screen.getByText(/not the same as/)).toBeInTheDocument();
  });
});

describe("ObservationList", () => {
  it("renders blood pressure components as recorded", () => {
    const { container } = render(
      <ObservationList title="Vital signs" observations={[observation()]} emptyText="none" />,
    );
    expect(container.textContent).toContain("138 mmHg / 88 mmHg");
  });

  it("leads with the value so it scans first", () => {
    const { container } = render(
      <ObservationList title="Vital signs" observations={[observation()]} emptyText="none" />,
    );
    expect(container.querySelector(".obs-value")?.textContent).toContain("138 mmHg / 88 mmHg");
  });

  it("states that no values are flagged because no reference ranges exist", () => {
    render(<ObservationList title="Vital signs" observations={[observation()]} emptyText="none" />);
    expect(screen.getByText("no reference ranges")).toBeInTheDocument();
  });

  it("never renders an abnormal indicator on the value row", () => {
    // Scoped to the row: the section note legitimately contains the words
    // "high, low, or abnormal" while explaining that nothing is flagged.
    const { container } = render(
      <ObservationList title="Vital signs" observations={[observation()]} emptyText="none" />,
    );
    const row = container.querySelector(".row");
    expect(row).not.toBeNull();
    expect(row?.textContent).not.toMatch(/\bhigh\b|\blow\b|abnormal|elevated|critical/i);
  });

  it("marks an absent category rather than assuming one", () => {
    render(
      <ObservationList
        title="Other"
        observations={[observation({ categoryDeclared: null })]}
        emptyText="none"
      />,
    );
    expect(screen.getByText("category not declared")).toBeInTheDocument();
  });

  it("shows an unresolved performer reference", () => {
    const { container } = render(
      <ObservationList
        title="Other"
        observations={[
          observation({
            performer: {
              reference: "Practitioner/practitioner-999",
              resolved: false,
              display: null,
              reason: "REFERENCE_TARGET_NOT_IN_BUNDLE",
            },
          }),
        ]}
        emptyText="none"
      />,
    );
    expect(container.textContent).toContain("Practitioner/practitioner-999 not present in bundle");
  });

  it("shows an empty state", () => {
    render(<ObservationList title="Vital signs" observations={[]} emptyText="No vitals." />);
    expect(screen.getByText("No vitals.")).toBeInTheDocument();
  });
});

describe("EncounterList", () => {
  it("renders an encounter with its type and date", () => {
    const { container } = render(<EncounterList encounters={[encounter()]} />);
    expect(container.textContent).toContain("Encounter for check up");
    expect(container.textContent).toContain("04 Nov 2025");
  });

  it("marks an encounter with no recorded type", () => {
    render(<EncounterList encounters={[encounter({ type: null })]} />);
    expect(screen.getByText("encounter type not recorded")).toBeInTheDocument();
  });

  it("shows an empty state", () => {
    render(<EncounterList encounters={[]} />);
    expect(screen.getByText("No encounters recorded.")).toBeInTheDocument();
  });
});

describe("OtherResults", () => {
  const reviewItem = {
    id: "observation-002",
    resourceType: "Observation",
    reasons: ["TERMINOLOGY_DISPLAY_UNRESOLVED", "OBSERVATION_CATEGORY_ABSENT"],
    summary: "LOINC 4548-4 (display unavailable)",
    detail: "The analyte cannot be named and the measurement cannot be classified.",
  };

  it("keeps a readable observation as a result, not in the review queue", () => {
    const weight = observation({
      id: "observation-003",
      categoryDeclared: null,
      components: [],
      value: 71.2,
      unit: "kg",
      code: coding({ code: "29463-7", display: "Body weight", systemName: "LOINC" }),
    });
    const { container } = render(<OtherResults observations={[weight]} needsReview={[]} />);
    expect(container.querySelector(".obs-value")?.textContent).toContain("71.2 kg");
    expect(container.querySelector(".subordinate")).toBeNull();
  });

  it("groups the review queue underneath, clearly subordinate", () => {
    const { container } = render(<OtherResults observations={[]} needsReview={[reviewItem]} />);
    const subordinate = container.querySelector(".subordinate");
    expect(subordinate).not.toBeNull();
    expect(subordinate?.textContent).toContain("Needs review — not presented as results");
  });

  it("explains why each item requires review", () => {
    render(<OtherResults observations={[]} needsReview={[reviewItem]} />);
    expect(
      screen.getByText("the code has no human-readable name in the source"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("no category, so the kind of measurement is unknown"),
    ).toBeInTheDocument();
  });

  it("states that nothing was silently dropped", () => {
    const { container } = render(<OtherResults observations={[]} needsReview={[reviewItem]} />);
    expect(container.textContent).toContain("nothing is silently dropped");
  });

  it("renders both groups together when both are present", () => {
    const { container } = render(
      <OtherResults observations={[observation()]} needsReview={[reviewItem]} />,
    );
    expect(container.querySelector(".obs-value")).not.toBeNull();
    expect(container.querySelector(".subordinate")).not.toBeNull();
  });

  it("renders nothing at all when there is neither", () => {
    const { container } = render(<OtherResults observations={[]} needsReview={[]} />);
    expect(container.firstChild).toBeNull();
  });
});

describe("GlanceStrip", () => {
  const data = {
    conditionsCurrent: [condition(), condition({ id: "c2" })],
    medicationsActive: [
      medication(),
      medication({
        id: "m3",
        attribution: { patientId: "p2", patientLabel: "MRN-48213-A", candidateId: "d", note: "" },
      }),
    ],
    allergiesCurrent: [allergy(), allergy({ id: "a2", criticality: "low", flags: ["unconfirmed"] })],
    needsReview: [
      { id: "o2", resourceType: "Observation", reasons: [], summary: "s", detail: "d" },
    ],
  } as never;

  it("counts the duplicate record's medication separately, never in the active total", () => {
    const { container } = render(<GlanceStrip data={data} issueCount={30} />);
    expect(container.textContent).toContain("1 active medication");
    expect(container.textContent).toContain("+ 1 from possible duplicate");
  });

  it("surfaces high-criticality allergies at a glance", () => {
    const { container } = render(<GlanceStrip data={data} issueCount={30} />);
    expect(container.textContent).toContain("2 allergies");
    expect(container.textContent).toContain("(1 high)");
    expect(container.textContent).toContain("1 unconfirmed");
  });

  it("reports the review queue and the issue count", () => {
    const { container } = render(<GlanceStrip data={data} issueCount={30} />);
    expect(container.textContent).toContain("1 needs review");
    expect(container.textContent).toContain("30 data-quality issues");
  });
});

describe("ExcludedDrawer", () => {
  it("labels retracted records as not current clinical facts", () => {
    render(<ExcludedDrawer items={[excluded()]} note="Retracted at source." />);
    expect(screen.getByText("not current clinical facts")).toBeInTheDocument();
  });

  it("names the field that caused the exclusion", () => {
    const { container } = render(<ExcludedDrawer items={[excluded()]} note="n" />);
    expect(container.textContent).toContain("Observation.status");
  });

  it("withholds a retracted value and says why", () => {
    const { container } = render(<ExcludedDrawer items={[excluded()]} note="n" />);
    expect(container.textContent).toContain("withheld");
    expect(container.textContent).not.toContain("14.7");
  });

  it("is collapsed by default", () => {
    const { container } = render(<ExcludedDrawer items={[excluded()]} note="n" />);
    expect(container.querySelector("details")?.hasAttribute("open")).toBe(false);
  });

  it("renders nothing when nothing was excluded", () => {
    const { container } = render(<ExcludedDrawer items={[]} note="n" />);
    expect(container.firstChild).toBeNull();
  });
});

describe("DuplicateEvidence", () => {
  const candidate: DuplicateCandidate = {
    candidateId: "dup-patient-001-patient-002",
    memberIds: ["patient-001", "patient-002"],
    determination: "unreconciled",
    confidence: "conflicted",
    canonicalPatientId: "patient-001",
    memberResourceIds: { "patient-001": ["a", "b"], "patient-002": ["c"] },
    mergePerformed: false,
    sourceAssertedLink: null,
    evidenceFor: [
      { signal: "family-name-match", detail: "Both give Whitfield.", strength: "weak", direction: "for" },
    ],
    evidenceAgainst: [
      {
        signal: "distinct-identifier-same-system",
        detail: "Different values from one assigning system.",
        strength: "strong",
        direction: "against",
      },
    ],
    recommendedAction: "human-steward-review-identifier-conflict",
  };

  it("states that the records were not merged", () => {
    render(<DuplicateEvidence candidate={candidate} rationale="Selected patient-001." />);
    expect(screen.getByText("not merged")).toBeInTheDocument();
  });

  it("shows evidence on both sides", () => {
    render(<DuplicateEvidence candidate={candidate} rationale="r" />);
    expect(screen.getByText("Evidence the records match")).toBeInTheDocument();
    expect(screen.getByText("Evidence against, or blocking confirmation")).toBeInTheDocument();
    expect(screen.getByText("family-name-match")).toBeInTheDocument();
    expect(screen.getByText("distinct-identifier-same-system")).toBeInTheDocument();
  });

  it("surfaces the confidence grade and recommended action", () => {
    const { container } = render(<DuplicateEvidence candidate={candidate} rationale="r" />);
    expect(container.textContent).toContain("conflicted");
    expect(container.textContent).toContain("human steward review identifier conflict");
  });

  it("marks a source-asserted link as reconciled by the source", () => {
    render(
      <DuplicateEvidence
        candidate={{ ...candidate, mergePerformed: true, determination: "source-asserted-link" }}
        rationale="r"
      />,
    );
    expect(screen.getByText("reconciled by source")).toBeInTheDocument();
  });
});

describe("DataQualityPanel", () => {
  it("summarises issues by severity", () => {
    render(
      <DataQualityPanel
        issues={[
          { code: "A", severity: "high", message: "m1", resourceId: null, resourceType: null, path: null, detail: {} },
          { code: "B", severity: "low", message: "m2", resourceId: null, resourceType: null, path: null, detail: {} },
        ]}
      />,
    );
    expect(screen.getByText("1 high")).toBeInTheDocument();
    expect(screen.getByText("1 low")).toBeInTheDocument();
  });

  it("lists each issue with its code", () => {
    const { container } = render(
      <DataQualityPanel
        issues={[
          {
            code: "REFERENCE_UNRESOLVED",
            severity: "medium",
            message: "Reference not in bundle.",
            resourceId: "condition-003",
            resourceType: "Condition",
            path: "Condition.encounter",
            detail: {},
          },
        ]}
      />,
    );
    expect(container.textContent).toContain("REFERENCE_UNRESOLVED");
    expect(container.textContent).toContain("condition-003");
  });
});

describe("cross-section separation", () => {
  it("a retracted summary never appears in a clinical section", () => {
    const { container } = render(
      <div>
        <ConditionList current={[condition()]} historical={[]} categoryDeclared={false} />
        <MedicationList active={[medication()]} historical={[]} />
      </div>,
    );
    expect(container.textContent).not.toContain("Creatinine");
    expect(container.textContent).not.toContain("14.7");
  });

  it("the attributed block is visually separated from the subject's own list", () => {
    const { container } = render(
      <MedicationList
        active={[
          medication(),
          medication({
            id: "medicationrequest-003",
            attribution: {
              patientId: "patient-002",
              patientLabel: "MRN-48213-A",
              candidateId: "dup-1",
              note: "NOT confirmed.",
            },
          }),
        ]}
        historical={[]}
      />,
    );
    const attributed = container.querySelector(".attributed");
    expect(attributed).not.toBeNull();
    expect(within(attributed as HTMLElement).getByText(/MRN-48213-A/)).toBeInTheDocument();
  });
});

describe("loading and error boundaries", () => {
  it("loading announces itself to assistive technology", async () => {
    const { default: Loading } = await import("@/app/loading");
    render(<Loading />);
    const status = screen.getByRole("status");
    expect(status).toHaveAttribute("aria-busy", "true");
    expect(screen.getByText(/Loading clinical snapshot/)).toBeInTheDocument();
  });

  it("loading mirrors the real layout so content does not reflow", async () => {
    const { default: Loading } = await import("@/app/loading");
    const { container } = render(<Loading />);
    expect(container.querySelector(".patient-header")).not.toBeNull();
    expect(container.querySelector(".grid")).not.toBeNull();
    expect(container.querySelectorAll(".card").length).toBe(6);
  });

  it("the error boundary shows no clinical data and no raw message", async () => {
    const { default: ErrorBoundary } = await import("@/app/error");
    const error = Object.assign(new Error("Patient Dorothy Whitfield leaked here"), {
      digest: "abc123",
    });
    const { container } = render(<ErrorBoundary error={error} reset={() => {}} />);
    expect(container.textContent).not.toContain("Dorothy");
    expect(container.textContent).toContain("abc123");
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("the error boundary offers a retry", async () => {
    const { default: ErrorBoundary } = await import("@/app/error");
    let retried = false;
    render(
      <ErrorBoundary
        error={new Error("boom")}
        reset={() => {
          retried = true;
        }}
      />,
    );
    screen.getByRole("button", { name: /try again/i }).click();
    expect(retried).toBe(true);
  });
});
