import {
  Badge,
  CodeCaveat,
  CodeLabel,
  Empty,
  FlagBadges,
  PartialDate,
  SectionNote,
} from "@/components/primitives";
import type { AllergyItem } from "@/lib/types";

export function AllergyList({ current, historical }: {
  current: AllergyItem[];
  historical: AllergyItem[];
}) {
  const hasMismatch = current.some((allergy) => allergy.code.codeSystemMismatch);

  return (
    <section className="card">
      <h2>Allergies &amp; intolerances</h2>
      {hasMismatch ? (
        <SectionNote>
          One record carries a code that does not validate against the code system it
          declares. Entries are <strong>not</strong> de-duplicated, because de-duplication
          would mean trusting those codes.
        </SectionNote>
      ) : null}

      {current.length === 0 ? (
        <Empty>No active allergies recorded. This is not the same as &ldquo;no known allergies&rdquo;.</Empty>
      ) : (
        current.map((allergy) => <Row key={allergy.id} allergy={allergy} />)
      )}

      {historical.length > 0 ? (
        <>
          <h3 style={{ marginTop: 18 }} className="muted">Resolved / inactive</h3>
          {historical.map((allergy) => <Row key={allergy.id} allergy={allergy} />)}
        </>
      ) : null}
    </section>
  );
}

function Row({ allergy }: { allergy: AllergyItem }) {
  return (
    <div className="row">
      <div className="row-head">
        <span className="row-title"><CodeLabel coding={allergy.code} /></span>
        {allergy.criticality === "high" ? (
          <Badge tone="danger" title="High criticality as recorded by the source.">
            high criticality
          </Badge>
        ) : allergy.criticality ? (
          <Badge tone="unknown" title="The source could not assess criticality.">
            {allergy.criticality.replace(/-/g, " ")}
          </Badge>
        ) : null}
        <FlagBadges flags={allergy.flags} />
      </div>
      <CodeCaveat coding={allergy.code} />
      <div className="row-meta">
        <span>Recorded: <PartialDate date={allergy.recordedDate} /></span>
        <span>Status: {allergy.clinicalStatus?.display ?? "unknown"}</span>
        <span>Verification: {allergy.verificationStatus?.display ?? "unknown"}</span>
      </div>
    </div>
  );
}
