import type { Warning } from "@/lib/types";

/**
 * Snapshot-level warnings. Rendered above every clinical section and not
 * dismissible: an unreconciled duplicate changes how the whole page should be
 * read, so it cannot be something the reader scrolls past.
 */
export function Banners({ warnings }: { warnings: Warning[] }) {
  if (warnings.length === 0) return null;
  return (
    <>
      {warnings.map((warning) => (
        <div key={warning.code} className={`banner banner-${warning.severity}`} role="alert">
          <span className="banner-icon" aria-hidden>
            {warning.severity === "high" ? "⚠" : "ⓘ"}
          </span>
          <div>
            <div className="banner-title">{TITLES[warning.code] ?? warning.code}</div>
            <div className="banner-body">{warning.message}</div>
          </div>
        </div>
      ))}
    </>
  );
}

const TITLES: Record<string, string> = {
  DUPLICATE_CANDIDATE_UNRECONCILED: "Possible duplicate record — not reconciled",
  SNAPSHOT_STALE: "This snapshot may be out of date",
};
