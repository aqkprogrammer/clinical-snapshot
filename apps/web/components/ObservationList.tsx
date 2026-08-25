import { CodeLabel, Empty, PartialDate, ReferenceLabel, SectionNote } from "@/components/primitives";
import type { ObservationItem } from "@/lib/types";

/**
 * Values are rendered exactly as recorded. No reference range exists anywhere in
 * this bundle, so no high/low flag, colour, or arrow is derived -- doing so
 * would be the application inventing a clinical assessment.
 */
export function ObservationList({ title, observations, emptyText }: {
  title: string;
  observations: ObservationItem[];
  emptyText: string;
}) {
  const noRanges = observations.length > 0 && observations.every((o) => !o.referenceRangeAvailable);

  return (
    <section className="card">
      <h2>{title}</h2>
      {noRanges ? (
        <SectionNote>
          No reference ranges or interpretations are present in the source, so no values
          are flagged as high, low, or abnormal.
        </SectionNote>
      ) : null}
      {observations.length === 0 ? (
        <Empty>{emptyText}</Empty>
      ) : (
        observations.map((observation) => <Row key={observation.id} observation={observation} />)
      )}
    </section>
  );
}

function Row({ observation }: { observation: ObservationItem }) {
  return (
    <div className="row">
      <div className="row-head">
        <span className="row-title"><CodeLabel coding={observation.code} /></span>
      </div>

      <div style={{ margin: "6px 0 2px", fontSize: 20, fontWeight: 600 }}>
        {observation.components.length > 0 ? (
          observation.components
            .map((component) => `${component.value ?? "—"} ${component.unit ?? ""}`.trim())
            .join(" / ")
        ) : observation.value !== null ? (
          `${observation.value} ${observation.unit ?? ""}`.trim()
        ) : (
          <span className="unknown-value" style={{ fontSize: 15 }}>no value recorded</span>
        )}
      </div>

      {observation.components.length > 0 ? (
        <div className="small muted">
          {observation.components
            .map((component) => component.code.display ?? component.code.code)
            .join(" / ")}
        </div>
      ) : null}

      <div className="row-meta">
        <span><PartialDate date={observation.effective} /></span>
        {observation.categoryDeclared ? (
          <span>Category: {observation.categoryDeclared}</span>
        ) : (
          <span className="unknown-value">category not declared</span>
        )}
        {observation.performer ? (
          <span>Performer: <ReferenceLabel reference={observation.performer} /></span>
        ) : null}
      </div>
    </div>
  );
}
