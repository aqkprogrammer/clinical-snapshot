import { InfoNote, SectionHead, sectionId } from "@/components/primitives";
import { ObservationList } from "@/components/ObservationList";
import type { NeedsReviewItem, ObservationItem } from "@/lib/types";

const TITLE = "Other results";

const REASONS: Record<string, string> = {
  TERMINOLOGY_DISPLAY_UNRESOLVED: "the code has no human-readable name in the source",
  OBSERVATION_CATEGORY_ABSENT: "no category, so the kind of measurement is unknown",
  DATE_PRECISION_REDUCED: "the date is recorded to year precision only",
};

/**
 * Results that are not vital signs, plus the queue that could not be presented
 * as results at all.
 *
 * The two are grouped because a clinician looking for "anything else measured"
 * should find both in one place -- but they are not equivalent, so the review
 * queue is visually subordinate and states why each item is there.
 *
 * The split itself is the backend's: an observation is withheld only when it
 * can be neither named nor classified. A readable value with a missing
 * category (body weight, say) still renders as a result, because the number
 * means something even when the metadata is incomplete.
 */
export function OtherResults({ observations, needsReview }: {
  observations: ObservationItem[];
  needsReview: NeedsReviewItem[];
}) {
  if (observations.length === 0 && needsReview.length === 0) return null;

  return (
    <section className="card" aria-labelledby={sectionId(TITLE)} id="sec-other-results">
      <SectionHead
        title={TITLE}
        note={
          <InfoNote label="no reference ranges">
            The source supplies no reference ranges or interpretations, so no value on this
            page is flagged as high, low, or abnormal.
          </InfoNote>
        }
      />

      <ObservationList
        title={TITLE}
        heading={false}
        observations={observations}
        emptyText="No other observations recorded."
      />

      {needsReview.length > 0 ? (
        <div className="subordinate">
          <div className="subordinate-title">
            <span aria-hidden>⚠</span>
            <span>Needs review — not presented as results</span>
          </div>
          <p className="review-why">
            These records could not be identified well enough to show as clinical results. They
            are listed so nothing is silently dropped.
          </p>
          <ul className="rows">
            {needsReview.map((item) => (
              <li key={item.id}>
                <div className="row">
                  <div className="row-head">
                    <span className="row-title unknown-value">{item.summary}</span>
                    <span className="badge badge-neutral">{item.resourceType}</span>
                  </div>
                  <ul className="review-reasons">
                    {item.reasons.map((reason) => (
                      <li key={reason}>{REASONS[reason] ?? reason}</li>
                    ))}
                  </ul>
                </div>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
