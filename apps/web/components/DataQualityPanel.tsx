import type { Issue } from "@/lib/types";

const ORDER = ["high", "medium", "low"] as const;
type Severity = (typeof ORDER)[number];

const TONE: Record<Severity, string> = { high: "danger", medium: "warn", low: "neutral" };

const MEANING: Record<Severity, string> = {
  high: "Affects what can safely be shown, or flags a contradiction in the source.",
  medium: "Information is missing or unresolvable; the page says so where it matters.",
  low: "Structural or cosmetic defects in the source that do not affect what is displayed.",
};

/**
 * Every issue detected while building this snapshot, grouped by severity.
 *
 * Grouped disclosure rather than filter chips: each severity is a real
 * `<details>`, so it is keyboard-operable and linkable with no client-side
 * JavaScript, and the counts stay readable when collapsed. Exhaustive by
 * design, folded so the exhaustiveness does not crowd out clinical content.
 */
export function DataQualityPanel({ issues }: { issues: Issue[] }) {
  const bySeverity = ORDER.map((severity) => ({
    severity,
    items: issues.filter((issue) => issue.severity === severity),
  })).filter((group) => group.items.length > 0);

  return (
    <details className="drawer">
      <summary>
        Data quality
        <span className="muted" style={{ fontWeight: 400 }}>
          {issues.length} issue{issues.length === 1 ? "" : "s"}
        </span>
        {bySeverity.map(({ severity, items }) => (
          <span key={severity} className={`badge badge-${TONE[severity]}`}>
            {items.length} {severity}
          </span>
        ))}
      </summary>
      <div className="drawer-body">
        <p className="section-note" style={{ marginTop: 12 }}>
          Everything the pipeline could not do cleanly. Each entry records a decision made
          about imperfect input rather than a silent fallback.
        </p>
        {bySeverity.map(({ severity, items }) => (
          <details key={severity} className="severity-group" open={severity === "high"}>
            <summary>
              <span className={`badge badge-${TONE[severity]}`}>{severity}</span>
              <span>
                {items.length} issue{items.length === 1 ? "" : "s"}
              </span>
              <span className="muted" style={{ fontWeight: 400, fontSize: 12 }}>
                {MEANING[severity]}
              </span>
            </summary>
            <ul className="rows">
              {items.map((issue, index) => (
                <li key={`${issue.code}-${issue.resourceId}-${index}`}>
                  <div className="issue-row" style={{ gridTemplateColumns: "1fr" }}>
                    <div>
                      <div>{issue.message}</div>
                      <div className="issue-code">
                        {issue.code}
                        {issue.resourceId ? ` · ${issue.resourceId}` : ""}
                        {issue.path ? ` · ${issue.path}` : ""}
                      </div>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          </details>
        ))}
      </div>
    </details>
  );
}
