import { CodeLabel, Empty, FlagBadges, PartialDate, ReferenceLabel, SectionNote } from "@/components/primitives";
import type { ConditionItem } from "@/lib/types";

export function ConditionList({ current, historical, categoryDeclared }: {
  current: ConditionItem[];
  historical: ConditionItem[];
  categoryDeclared: boolean;
}) {
  return (
    <section className="card">
      <h2>Conditions</h2>
      {!categoryDeclared ? (
        <SectionNote>
          No source record declares <code>Condition.category</code>, so these cannot be
          identified as problem-list items or encounter diagnoses. This is not a problem list.
        </SectionNote>
      ) : null}

      {current.length === 0 ? (
        <Empty>No active conditions recorded.</Empty>
      ) : (
        current.map((condition) => <Row key={condition.id} condition={condition} />)
      )}

      {historical.length > 0 ? (
        <>
          <h3 style={{ marginTop: 18 }} className="muted">Resolved / inactive</h3>
          {historical.map((condition) => <Row key={condition.id} condition={condition} />)}
        </>
      ) : null}
    </section>
  );
}

function Row({ condition }: { condition: ConditionItem }) {
  return (
    <div className="row">
      <div className="row-head">
        <span className="row-title"><CodeLabel coding={condition.code} /></span>
        <FlagBadges flags={condition.flags} />
      </div>
      <div className="row-meta">
        <span>Onset: <PartialDate date={condition.onset} /></span>
        <span>Status: {condition.clinicalStatus?.display ?? "unknown"}</span>
        <span>
          Verification: {condition.verificationStatus?.display ?? "unknown"}
        </span>
        <span>Encounter: <ReferenceLabel reference={condition.encounter} /></span>
      </div>
    </div>
  );
}
