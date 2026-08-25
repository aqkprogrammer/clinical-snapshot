import type { Warning } from "@/lib/types";

export interface DuplicateContext {
  /** A record number a clinician recognises, never a database id. */
  label: string;
  /** Active medications carried by that record, already attributed below. */
  medicationCount: number;
}

/**
 * Snapshot-level warnings, compact.
 *
 * The headline and the one fact a clinician must act on stay on screen; the
 * source's full wording folds away behind "Why". Nothing is removed -- an
 * unreconciled duplicate changes how the whole page should be read, so the
 * banner is not dismissible and its severity colour is unchanged.
 *
 * `role="status"` rather than `role="alert"`: these are present on first paint,
 * and an assertive role interrupts a screen reader mid-page for content that
 * was never dynamic.
 */
export function Banners({
  warnings,
  duplicate,
}: {
  warnings: Warning[];
  duplicate?: DuplicateContext;
}) {
  if (warnings.length === 0) return null;
  return (
    <div role="status" aria-label="Snapshot warnings">
      {warnings.map((warning) => (
        <div key={warning.code} className={`banner banner-${warning.severity}`}>
          <span className="banner-icon" aria-hidden>
            {warning.severity === "high" ? "⚠" : "ⓘ"}
          </span>
          <div className="banner-main">
            <div className="banner-line">
              <span className="banner-title">{title(warning)}</span>
              <span className="banner-body">
                <span className="banner-summary">{summary(warning, duplicate)}</span>{" "}
                <details>
                  <summary>Why</summary>
                  <p>{warning.message}</p>
                </details>
              </span>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function title(warning: Warning): string {
  switch (warning.code) {
    case "DUPLICATE_CANDIDATE_UNRECONCILED":
      return "Possible duplicate record";
    case "SNAPSHOT_STALE":
      return "Snapshot may be out of date";
    default:
      return warning.code.replace(/_/g, " ").toLowerCase();
  }
}

function summary(warning: Warning, duplicate?: DuplicateContext): string {
  if (warning.code === "DUPLICATE_CANDIDATE_UNRECONCILED") {
    const other = duplicate ? `Record ${duplicate.label}` : "Another record in this bundle";
    const count = duplicate?.medicationCount ?? 0;
    const holding =
      count > 0
        ? ` It holds ${count} active medication${count === 1 ? "" : "s"}, shown separately below.`
        : "";
    return `${other} may be the same person — unconfirmed, so the records are not merged.${holding}`;
  }
  if (warning.code === "SNAPSHOT_STALE") {
    const days = warning.detail.daysSinceLatestActivity;
    return days
      ? `${days} days since the last recorded activity — statuses reflect the export, not today.`
      : "Statuses reflect the export date, not today.";
  }
  return warning.message;
}
