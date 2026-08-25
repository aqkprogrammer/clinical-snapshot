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
import { NeedsReviewList } from "@/components/NeedsReviewList";
import { ObservationList } from "@/components/ObservationList";
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

  it("shows a missing US Core birthsex as not recorded", () => {
    render(<PatientHeader patient={patient()} meta={meta} />);
    const facts = screen.getByText("Birth sex (US Core)").parentElement;
    expect(facts?.textContent).toContain("not recorded");
  });

  it("surfaces the data-as-of date", () => {
    const { container } = render(<PatientHeader patient={patient()} meta={meta} />);
    expect(container.textContent).toContain("2026-06-01");
  });

  it("flags a record that makes no profile claim", () => {
    render(<PatientHeader patient={patient({ profilesClaimed: [] })} meta={meta} />);
    expect(screen.getByText("no profile claim")).toBeInTheDocument();
  });
});

describe("Banners", () => {
  it("renders the unreconciled-duplicate warning prominently", () => {
    render(
      <Banners
        warnings={[
          {
            code: "DUPLICATE_CANDIDATE_UNRECONCILED",
            severity: "high",
            message: "A possible duplicate Patient record shares this patient's name.",
            detail: {},
          },
        ]}
      />,
    );
    expect(screen.getByText("Possible duplicate record — not reconciled")).toBeInTheDocument();
  });

  it("renders nothing when there are no warnings", () => {
    const { container } = render(<Banners warnings={[]} />);
    expect(container.firstChild).toBeNull();
  });
});

describe("ConditionList", () => {
  it("declares that the source did not say whether these are problem-list items", () => {
    render(<ConditionList current={[condition()]} historical={[]} categoryDeclared={false} />);
    expect(screen.getByText(/This is not a problem list/)).toBeInTheDocument();
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
    expect(screen.getByText("No longer active — do not treat as current")).toBeInTheDocument();
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
    expect(screen.getByText("high criticality")).toBeInTheDocument();
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
    expect(screen.getByText(/not.*de-duplicated/)).toBeInTheDocument();
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

  it("states that no values are flagged because no reference ranges exist", () => {
    render(<ObservationList title="Vital signs" observations={[observation()]} emptyText="none" />);
    expect(screen.getByText(/no values are.*flagged as high, low, or abnormal/)).toBeInTheDocument();
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

describe("NeedsReviewList", () => {
  it("explains why an item is not shown as a clinical result", () => {
    render(
      <NeedsReviewList
        items={[
          {
            id: "observation-002",
            resourceType: "Observation",
            reasons: ["TERMINOLOGY_DISPLAY_UNRESOLVED", "OBSERVATION_CATEGORY_ABSENT"],
            summary: "LOINC 4548-4 (display unavailable)",
            detail: "The analyte cannot be named and the measurement cannot be classified.",
          },
        ]}
      />,
    );
    expect(screen.getByText(/not shown as clinical results/i)).toBeInTheDocument();
    expect(screen.getByText("no human-readable name for the code")).toBeInTheDocument();
  });

  it("renders nothing when there is nothing to review", () => {
    const { container } = render(<NeedsReviewList items={[]} />);
    expect(container.firstChild).toBeNull();
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
