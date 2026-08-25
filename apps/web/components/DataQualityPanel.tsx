import type { Issue } from "@/lib/types";

/**
 * Every issue detected while building the snapshot. Exhaustive by design, and
 * collapsed by default so the exhaustiveness does not crowd out the clinical
 * content.
 */
export function DataQualityPanel({ issues }: { issues: Issue[] }) {
  const counts = issues.reduce<Record<string, number>>((acc, issue) => {
    acc[issue.severity] = (acc[issue.severity] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <details className="drawer">
      <summary>
        Data quality — {issues.length} issue{issues.length === 1 ? "" : "s"}
        {(["high", "medium", "low"] as const).map((severity) =>
          counts[severity] ? (
            <span
              key={severity}
              className={`badge badge-${severity === "high" ? "danger" : severity === "medium" ? "warn" : "neutral"}`}
              style={{ marginLeft: 6 }}
            >
              {counts[severity]} {severity}
            </span>
          ) : null,
        )}
      </summary>
      <div className="drawer-body">
        <p className="section-note" style={{ marginTop: 12 }}>
          Everything the pipeline could not do cleanly. Each entry records a decision
          made about imperfect input rather than a silent fallback.
        </p>
        {issues.map((issue, index) => (
          <div key={`${issue.code}-${issue.resourceId}-${index}`} className="issue-row">
            <div>
              <span
                className={`badge badge-${issue.severity === "high" ? "danger" : issue.severity === "medium" ? "warn" : "neutral"}`}
              >
                {issue.severity}
              </span>
            </div>
            <div>
              <div>{issue.message}</div>
              <div className="issue-code">
                {issue.code}
                {issue.resourceId ? ` · ${issue.resourceId}` : ""}
                {issue.path ? ` · ${issue.path}` : ""}
              </div>
            </div>
          </div>
        ))}
      </div>
    </details>
  );
}
