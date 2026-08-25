import type { SnapshotData } from "@/lib/types";

/**
 * At-a-glance counts.
 *
 * Purely derived from what is already rendered further down the page -- no new
 * data, no new clinical assertion. It exists so the first viewport answers
 * "how much is there, and is anything urgent?" without reading four cards.
 *
 * The duplicate record's medication is counted separately and labelled as
 * such: rolling it into the active total would be the merge this application
 * refuses to perform.
 */
export function GlanceStrip({ data, issueCount }: { data: SnapshotData; issueCount: number }) {
  const own = data.medicationsActive.filter((m) => !m.attribution).length;
  const attributed = data.medicationsActive.length - own;
  const highCriticality = data.allergiesCurrent.filter((a) => a.criticality === "high").length;
  const unconfirmed = data.allergiesCurrent.filter((a) => a.flags.includes("unconfirmed")).length;

  return (
    <nav className="glance" aria-label="Snapshot summary">
      <a href="#sec-active-problems">
        <strong>{data.conditionsCurrent.length}</strong> active problem
        {data.conditionsCurrent.length === 1 ? "" : "s"}
      </a>
      <span className="sep" aria-hidden>·</span>
      <a href="#sec-medications">
        <strong>{own}</strong> active medication{own === 1 ? "" : "s"}
        {attributed > 0 ? (
          <span className="glance-flag">
            {" "}
            + {attributed} from possible duplicate
          </span>
        ) : null}
      </a>
      <span className="sep" aria-hidden>·</span>
      <a href="#sec-allergies-intolerances">
        <strong>{data.allergiesCurrent.length}</strong> allerg
        {data.allergiesCurrent.length === 1 ? "y" : "ies"}
        {highCriticality > 0 ? <span className="glance-flag"> ({highCriticality} high)</span> : null}
        {unconfirmed > 0 ? <span className="muted"> · {unconfirmed} unconfirmed</span> : null}
      </a>
      {data.needsReview.length > 0 ? (
        <>
          <span className="sep" aria-hidden>·</span>
          <a href="#sec-other-results">
            <strong>{data.needsReview.length}</strong> need
            {data.needsReview.length === 1 ? "s" : ""} review
          </a>
        </>
      ) : null}
      <span className="sep" aria-hidden>·</span>
      <a href="#record-integrity" className="muted">
        {issueCount} data-quality {issueCount === 1 ? "issue" : "issues"}
      </a>
    </nav>
  );
}
