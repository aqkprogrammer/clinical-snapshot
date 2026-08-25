import {
  CodeCaveat,
  CodeLabel,
  Empty,
  FlagBadges,
  InfoNote,
  PartialDate,
  ReferenceLabel,
  SectionHead,
  sectionId,
} from "@/components/primitives";
import type { ConditionItem } from "@/lib/types";

const TITLE = "Active problems";

export function ConditionList({ current, historical, categoryDeclared }: {
  current: ConditionItem[];
  historical: ConditionItem[];
  categoryDeclared: boolean;
}) {
  return (
    <section className="card" aria-labelledby={sectionId(TITLE)}>
      <SectionHead
        title={TITLE}
        note={
          !categoryDeclared ? (
            <InfoNote label="not a formal problem list">
              No source record declares <code>Condition.category</code>, so these cannot be
              identified as problem-list items or encounter diagnoses. They are the conditions
              the source recorded as active, nothing more.
            </InfoNote>
          ) : undefined
        }
      />

      {current.length === 0 ? (
        <Empty>No active conditions recorded.</Empty>
      ) : (
        <ul className="rows">
          {current.map((condition) => (
            <li key={condition.id}>
              <Row condition={condition} />
            </li>
          ))}
        </ul>
      )}

      {historical.length > 0 ? (
        <div className="subordinate">
          <div className="subordinate-title">Resolved / inactive</div>
          <ul className="rows">
            {historical.map((condition) => (
              <li key={condition.id}>
                <Row condition={condition} />
              </li>
            ))}
          </ul>
        </div>
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
        <span>Onset <PartialDate date={condition.onset} /></span>
        <span>{condition.clinicalStatus?.display ?? "status unknown"}</span>
        <span>{condition.verificationStatus?.display ?? "verification unknown"}</span>
        {condition.encounter ? (
          <span>Encounter: <ReferenceLabel reference={condition.encounter} /></span>
        ) : null}
      </div>
      <CodeCaveat coding={condition.code} />
    </div>
  );
}
