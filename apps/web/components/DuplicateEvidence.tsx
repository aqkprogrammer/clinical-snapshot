import type { DuplicateCandidate } from "@/lib/types";

const STRENGTH_TONE: Record<string, string> = {
  decisive: "badge-danger",
  strong: "badge-danger",
  moderate: "badge-warn",
  weak: "badge-neutral",
  "very-weak": "badge-neutral",
  "suggestive-only": "badge-unknown",
  "blocks-confirmation": "badge-unknown",
  neutral: "badge-neutral",
};

/**
 * The evidence on both sides of the identity question, so a reviewer can see
 * why the records were not merged and make the call themselves.
 */
export function DuplicateEvidence({ candidate, rationale, labels = {} }: {
  candidate: DuplicateCandidate;
  rationale: string;
  /** Record id -> the number a clinician recognises, e.g. an MRN. */
  labels?: Record<string, string>;
}) {
  return (
    <details className="drawer">
      <summary>
        Identity analysis
        <span className={`chip ${candidate.mergePerformed ? "" : "chip-warn"}`}>
          {candidate.mergePerformed ? "reconciled by source" : "not merged"}
        </span>
        <span className="muted" style={{ fontWeight: 400, fontSize: 12 }}>
          why these records were not combined
        </span>
      </summary>
      <div className="drawer-body">
        <p className="section-note" style={{ marginTop: 12 }}>{rationale}</p>
        <p className="small">
          Determination: <strong>{candidate.determination}</strong> · Confidence:{" "}
          <strong>{candidate.confidence}</strong> · Recommended action:{" "}
          <strong>{candidate.recommendedAction.replace(/-/g, " ")}</strong>
        </p>
        <p className="small muted">
          {Object.entries(candidate.memberResourceIds).map(([id, resources]) => (
            <span key={id} style={{ marginRight: 16 }}>
              {labels[id] ?? id}: {resources.length} displayable record
              {resources.length === 1 ? "" : "s"}
            </span>
          ))}
        </p>
        <p className="small muted" style={{ marginTop: 10 }}>
          The evidence below is the system&apos;s own record of the decision, quoted verbatim.
        </p>
        <div className="evidence-cols" style={{ marginTop: 12 }}>
          <div>
            <h3>Evidence the records match</h3>
            {candidate.evidenceFor.map((evidence) => (
              <div key={evidence.signal} className="evidence-item">
                <div>
                  <span className={`badge ${STRENGTH_TONE[evidence.strength] ?? "badge-neutral"}`}>
                    {evidence.strength.replace(/-/g, " ")}
                  </span>{" "}
                  <span className="evidence-signal">{evidence.signal}</span>
                </div>
                <div className="muted" style={{ marginTop: 3 }}>{evidence.detail}</div>
              </div>
            ))}
          </div>
          <div>
            <h3>Evidence against, or blocking confirmation</h3>
            {candidate.evidenceAgainst.map((evidence) => (
              <div key={evidence.signal} className="evidence-item">
                <div>
                  <span className={`badge ${STRENGTH_TONE[evidence.strength] ?? "badge-neutral"}`}>
                    {evidence.strength.replace(/-/g, " ")}
                  </span>{" "}
                  <span className="evidence-signal">{evidence.signal}</span>
                </div>
                <div className="muted" style={{ marginTop: 3 }}>{evidence.detail}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </details>
  );
}
