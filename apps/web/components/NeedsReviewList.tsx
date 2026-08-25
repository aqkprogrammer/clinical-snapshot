import type { NeedsReviewItem } from "@/lib/types";

const REASONS: Record<string, string> = {
  TERMINOLOGY_DISPLAY_UNRESOLVED: "no human-readable name for the code",
  OBSERVATION_CATEGORY_ABSENT: "no category, so the kind of measurement is unknown",
  DATE_PRECISION_REDUCED: "date recorded to year precision only",
};

/**
 * Records that could not be placed in a clinical section. They are surfaced
 * here rather than guessed into one -- a bare "6.1 %" with no analyte name in a
 * results table invites the reader to supply a meaning we do not have.
 */
export function NeedsReviewList({ items }: { items: NeedsReviewItem[] }) {
  if (items.length === 0) return null;
  return (
    <section className="card">
      <h2>Needs review — not shown as clinical results</h2>
      {items.map((item) => (
        <div key={item.id} className="row">
          <div className="row-head">
            <span className="row-title unknown-value">{item.summary}</span>
            <span className="badge badge-neutral">{item.resourceType}</span>
          </div>
          <div className="small" style={{ marginTop: 4 }}>{item.detail}</div>
          <ul className="small muted" style={{ margin: "6px 0 0", paddingLeft: 18 }}>
            {item.reasons.map((reason) => (
              <li key={reason}>{REASONS[reason] ?? reason}</li>
            ))}
          </ul>
        </div>
      ))}
    </section>
  );
}
