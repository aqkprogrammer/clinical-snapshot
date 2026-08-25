import {
  CodeCaveat,
  CodeLabel,
  Empty,
  FlagBadges,
  PartialDate,
  SectionHead,
  sectionId,
} from "@/components/primitives";
import type { MedicationItem } from "@/lib/types";

const TITLE = "Medications";

/**
 * Three groups that must never be mistaken for one another.
 *
 * Each carries a persistent label rather than relying on position or colour
 * alone, because "which of these is the patient actually taking?" is the
 * question this card exists to answer:
 *
 *   CURRENT                  the subject's own active orders
 *   FROM POSSIBLE DUPLICATE  another record's active order, attributed, never
 *                            counted as this patient's
 *   STOPPED                  real history, explicitly not current
 */
export function MedicationList({ active, historical }: {
  active: MedicationItem[];
  historical: MedicationItem[];
}) {
  const own = active.filter((m) => !m.attribution);
  const attributed = active.filter((m) => m.attribution);

  return (
    <section className="card" aria-labelledby={sectionId(TITLE)}>
      <SectionHead title={TITLE} />

      <div className="med-group">
        <div className="med-group-label med-group-current">
          <span>Current</span>
          <span className="med-group-note">taken by this patient</span>
        </div>
        {own.length === 0 ? (
          <Empty>No active medications recorded.</Empty>
        ) : (
          <ul className="rows">
            {own.map((medication) => (
              <li key={medication.id}>
                <Row medication={medication} />
              </li>
            ))}
          </ul>
        )}
      </div>

      {attributed.map((medication) => (
        <div key={medication.id} className="attributed">
          <div className="attribution-note">
            <span aria-hidden>⚠</span>
            <span>From possible duplicate — {medication.attribution?.patientLabel}</span>
            <span className="attribution-detail">
              Same-person status is <strong>NOT confirmed</strong>, so this is not counted as
              this patient&apos;s medication. Shown because omitting an active order would be
              unsafe if the records do turn out to match.
            </span>
          </div>
          <Row medication={medication} />
        </div>
      ))}

      {historical.length > 0 ? (
        <div className="med-group">
          <div className="med-group-label med-group-stopped">
            <span>Stopped</span>
            <span className="med-group-note">not current — do not treat as active</span>
          </div>
          <ul className="rows">
            {historical.map((medication) => (
              <li key={medication.id}>
                <Row medication={medication} stopped />
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

function Row({ medication, stopped = false }: { medication: MedicationItem; stopped?: boolean }) {
  return (
    <div className={stopped ? "row stopped-row" : "row"}>
      <div className="row-head">
        <span className="row-title"><CodeLabel coding={medication.medication} /></span>
        {medication.status && medication.status !== "active" ? (
          <span className="badge badge-neutral">{medication.status}</span>
        ) : null}
        <FlagBadges flags={medication.flags} />
      </div>
      <div className="row-meta">
        <span>
          {medication.dosageText ?? <span className="unknown-value">no dosage recorded</span>}
        </span>
        <span>Ordered <PartialDate date={medication.authoredOn} /></span>
      </div>
      <CodeCaveat coding={medication.medication} />
    </div>
  );
}
