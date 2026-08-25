/**
 * The uncertainty primitives.
 *
 * These are the highest-value frontend tests in the repo: every place the UI
 * could imply more confidence than the data supports passes through one of
 * these four components.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  Badge,
  CodeLabel,
  Empty,
  FlagBadges,
  PartialDate,
  ReferenceLabel,
} from "@/components/primitives";
import { coding, fullDate, instant, mismatchedCoding, undisplayedCoding, yearOnly } from "./fixtures";

describe("PartialDate", () => {
  it("marks a year-only date as year-only instead of widening it", () => {
    render(<PartialDate date={yearOnly} />);
    expect(screen.getByText("2019", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("(year only)")).toBeInTheDocument();
  });

  it("never renders a month or day for a year-precision value", () => {
    const { container } = render(<PartialDate date={yearOnly} />);
    expect(container.textContent).not.toMatch(/Jan|January|01-01/);
  });

  it("marks a month-only date as month-only", () => {
    render(<PartialDate date={{ value: "2019-07", precision: "month" }} />);
    expect(screen.getByText("(month only)")).toBeInTheDocument();
    expect(screen.getByText(/Jul 2019/)).toBeInTheDocument();
  });

  it("formats a full date without a precision caveat", () => {
    const { container } = render(<PartialDate date={fullDate} />);
    expect(container.textContent).toContain("12 Mar 1958");
    expect(container.textContent).not.toContain("only");
  });

  it("formats an instant in UTC", () => {
    const { container } = render(<PartialDate date={instant} />);
    expect(container.textContent).toContain("04 Nov 2025");
    expect(container.textContent).toContain("UTC");
  });

  it("says 'not recorded' rather than rendering blank when absent", () => {
    render(<PartialDate date={null} />);
    expect(screen.getByText("not recorded")).toBeInTheDocument();
  });
});

describe("CodeLabel", () => {
  it("renders a source-supplied display with its code", () => {
    const { container } = render(<CodeLabel coding={coding()} />);
    expect(container.textContent).toContain("Essential (primary) hypertension");
    expect(container.textContent).toContain("ICD-10-CM I10");
  });

  it("says the display is unavailable rather than inventing one", () => {
    const { container } = render(<CodeLabel coding={undisplayedCoding} />);
    expect(container.textContent).toContain("ICD-10-CM E11.9 — display unavailable");
    expect(screen.getByText("no display")).toBeInTheDocument();
  });

  it("does not fall back to showing the bare code as if it were a name", () => {
    const { container } = render(<CodeLabel coding={undisplayedCoding} />);
    // the code appears only inside the explicit "display unavailable" phrasing
    expect(container.textContent).not.toMatch(/^E11\.9$/);
  });

  it("flags a display whose code does not validate against its system", () => {
    const { container } = render(<CodeLabel coding={mismatchedCoding} />);
    expect(container.textContent).toContain("Penicillin");
    expect(screen.getByText("code / system mismatch")).toBeInTheDocument();
  });

  it("keeps the label of a mismatched code rather than hiding it", () => {
    render(<CodeLabel coding={mismatchedCoding} />);
    expect(screen.getByText("Penicillin")).toBeInTheDocument();
  });

  it("attributes a display resolved from the curated map", () => {
    render(
      <CodeLabel
        coding={coding({
          display: "Confirmed",
          displayStatus: "resolved-local",
          displaySource: "verified-local-map",
          displaySourceDetail: "FHIR R4 CodeSystem condition-ver-status",
        })}
      />,
    );
    expect(screen.getByText("spec display")).toBeInTheDocument();
  });
});

describe("ReferenceLabel", () => {
  it("distinguishes an unresolved reference from an absent one", () => {
    const { container } = render(
      <ReferenceLabel
        reference={{
          reference: "Encounter/encounter-099",
          resolved: false,
          display: null,
          reason: "REFERENCE_TARGET_NOT_IN_BUNDLE",
        }}
      />,
    );
    expect(container.textContent).toContain("unresolved");
    expect(container.textContent).toContain("Encounter/encounter-099 not present in bundle");
  });

  it("says 'not recorded' when the source recorded no reference at all", () => {
    render(<ReferenceLabel reference={null} />);
    expect(screen.getByText("not recorded")).toBeInTheDocument();
  });

  it("shows the target label when resolved", () => {
    render(
      <ReferenceLabel
        reference={{
          reference: "Encounter/encounter-001",
          resolved: true,
          display: "Encounter for check up",
          reason: null,
        }}
      />,
    );
    expect(screen.getByText("Encounter for check up")).toBeInTheDocument();
  });
});

describe("FlagBadges", () => {
  it("renders an unconfirmed caveat with a text label, not colour alone", () => {
    render(<FlagBadges flags={["unconfirmed"]} />);
    expect(screen.getByText("unconfirmed")).toBeInTheDocument();
  });

  it("renders nothing when there are no flags", () => {
    const { container } = render(<FlagBadges flags={[]} />);
    expect(container.textContent).toBe("");
  });

  it("falls back to the raw flag name for an unknown flag", () => {
    render(<FlagBadges flags={["some-new-flag"]} />);
    expect(screen.getByText("some-new-flag")).toBeInTheDocument();
  });
});

describe("Badge and Empty", () => {
  it("badges carry readable text", () => {
    render(<Badge tone="danger">high criticality</Badge>);
    expect(screen.getByText("high criticality")).toBeInTheDocument();
  });

  it("empty states are explicit", () => {
    render(<Empty>No active medications recorded.</Empty>);
    expect(screen.getByText("No active medications recorded.")).toBeInTheDocument();
  });
});
