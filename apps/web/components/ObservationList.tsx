import {
  CodeCaveat,
  CodeLabel,
  Empty,
  InfoNote,
  PartialDate,
  ReferenceLabel,
  SectionHead,
  sectionId,
} from "@/components/primitives";
import type { ObservationItem } from "@/lib/types";

/**
 * Value first.
 *
 * A vital sign is scanned as a number, so the number is the largest thing in
 * the row and the analyte name sits under it. Values are rendered exactly as
 * recorded -- no reference range exists anywhere in this bundle, so no high /
 * low / abnormal indicator is derived. Doing so would be the application
 * inventing a clinical assessment.
 */
export function ObservationList({ title, observations, emptyText, heading = true }: {
  title: string;
  observations: ObservationItem[];
  emptyText: string;
  heading?: boolean;
}) {
  const noRanges = observations.length > 0 && observations.every((o) => !o.referenceRangeAvailable);
  const body = (
    <>
      {observations.length === 0 ? (
        <Empty>{emptyText}</Empty>
      ) : (
        <ul className="rows">
          {observations.map((observation) => (
            <li key={observation.id}>
              <Row observation={observation} />
            </li>
          ))}
        </ul>
      )}
    </>
  );

  if (!heading) return body;

  return (
    <section className="card" aria-labelledby={sectionId(title)}>
      <SectionHead
        title={title}
        note={
          noRanges ? (
            <InfoNote label="no reference ranges">
              The source supplies no reference ranges or interpretations, so no value on this
              page is flagged as high, low, or abnormal. Read the numbers against your own
              reference ranges.
            </InfoNote>
          ) : undefined
        }
      />
      {body}
    </section>
  );
}

function Row({ observation }: { observation: ObservationItem }) {
  const value =
    observation.components.length > 0
      ? observation.components
          .map((c) => `${c.value ?? "—"} ${c.unit ?? ""}`.trim())
          .join(" / ")
      : observation.value !== null
        ? `${observation.value} ${observation.unit ?? ""}`.trim()
        : null;

  return (
    <div className="row">
      <div className="obs-value">
        {value ?? <span className="unknown-value">no value recorded</span>}
      </div>
      <div className="row-head">
        <span className="row-title" style={{ fontWeight: 500, fontSize: 14 }}>
          <CodeLabel coding={observation.code} />
        </span>
      </div>
      <div className="row-meta">
        <span><PartialDate date={observation.effective} /></span>
        {observation.categoryDeclared ? (
          <span>{observation.categoryDeclared}</span>
        ) : (
          <span className="unknown-value" title="The source declared no Observation.category.">
            category not declared
          </span>
        )}
        {observation.components.length > 0 ? (
          <span className="muted">
            {observation.components.map((c) => c.code.display ?? c.code.code).join(" / ")}
          </span>
        ) : null}
        {observation.performer ? (
          <span>Performer: <ReferenceLabel reference={observation.performer} /></span>
        ) : null}
      </div>
      <CodeCaveat coding={observation.code} />
    </div>
  );
}
