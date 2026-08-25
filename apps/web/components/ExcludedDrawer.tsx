import type { ExcludedItem } from "@/lib/types";

/**
 * Retracted resources.
 *
 * Collapsed by default and deliberately hard to mistake for the clinical
 * summary -- but present, because silently deleting a retracted result looks
 * identical to one that was never recorded, and the fact that a retraction
 * happened is itself clinically meaningful.
 */
export function ExcludedDrawer({ items, note }: { items: ExcludedItem[]; note: string }) {
  if (items.length === 0) return null;
  return (
    <details className="drawer">
      <summary>
        Retracted at source
        <span className="chip chip-danger">{items.length}</span>
        <span className="badge badge-danger">not current clinical facts</span>
      </summary>
      <div className="drawer-body">
        <p className="section-note" style={{ marginTop: 12 }}>{note}</p>
        {items.map((item) => (
          <div key={item.id} className="excluded-row">
            <div className="row-head">
              <span className="row-title" style={{ textDecoration: "line-through", color: "var(--muted)" }}>
                {item.summary}
              </span>
              <span className="badge badge-neutral">{item.resourceType}</span>
            </div>
            <div className="row-meta">
              <span>
                Entered in error, via <span className="mono">{item.suppressionField}</span>
              </span>
            </div>
            {item.valueWithheld ? (
              <div className="withheld">{item.valueWithheldReason}</div>
            ) : null}
          </div>
        ))}
      </div>
    </details>
  );
}
