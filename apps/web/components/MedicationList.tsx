import {
  CodeCaveat,
  CodeLabel,
  Empty,
  FlagBadges,
  PartialDate,
} from "@/components/primitives";
import type { MedicationItem } from "@/lib/types";

/**
 * Active and historical medications are separated structurally, not by a badge.
 * A stopped drug must never appear in the same visual list as a current one.
 *
 * Medications belonging to an unreconciled duplicate record appear in their own
 * attributed block below the subject's own list -- shown, because hiding an
 * active order is also a safety failure, but never mixed in.
 */
export function MedicationList({ active, historical }: {
  active: MedicationItem[];
  historical: MedicationItem[];
}) {
  const own = active.filter((m) => !m.attribution);
  const attributed = active.filter((m) => m.attribution);

  return (
    <section className="card">
      <h2>Medications</h2>

      <h3>Active</h3>
      {own.length === 0 ? <Empty>No active medications recorded.</Empty> : null}
      {own.map((medication) => <Row key={medication.id} medication={medication} />)}

      {attributed.map((medication) => (
        <div key={medication.id} className="attributed">
          <span className="attribution-note">
            {"⚠"} From {medication.attribution?.patientLabel} — a possible duplicate
            record. Same-person status is NOT confirmed, so this is not counted as this
            patient&apos;s medication.
          </span>
          <Row medication={medication} />
        </div>
      ))}

      {historical.length > 0 ? (
        <>
          <h3 style={{ marginTop: 18 }} className="muted">
            No longer active — do not treat as current
          </h3>
          {historical.map((medication) => <Row key={medication.id} medication={medication} />)}
        </>
      ) : null}
    </section>
  );
}

function Row({ medication }: { medication: MedicationItem }) {
  return (
    <div className="row">
      <div className="row-head">
        <span className="row-title"><CodeLabel coding={medication.medication} /></span>
        {medication.status && medication.status !== "active" ? (
          <span className="badge badge-neutral">{medication.status}</span>
        ) : null}
        <FlagBadges flags={medication.flags} />
      </div>
      <CodeCaveat coding={medication.medication} />
      <div className="row-meta">
        <span>{medication.dosageText ?? <span className="unknown-value">no dosage recorded</span>}</span>
        <span>Ordered: <PartialDate date={medication.authoredOn} /></span>
      </div>
    </div>
  );
}
