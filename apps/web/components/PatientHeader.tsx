import { Badge, PartialDate } from "@/components/primitives";
import { deriveAge } from "@/lib/age";
import type { PatientDetail, SnapshotMeta } from "@/lib/types";

/**
 * Identity first.
 *
 * Line one carries only what a clinician uses to confirm they have the right
 * patient: name, sex, age, date of birth, record number. Everything else --
 * race, ethnicity, address, contact -- is real data that belongs in the record
 * but does not belong in the first line of a scan, so it folds away.
 */
export function PatientHeader({ patient, meta }: { patient: PatientDetail; meta: SnapshotMeta }) {
  const name = [...patient.givenNames, patient.familyName].filter(Boolean).join(" ");
  const mrn = patient.identifiers.find((i) => i.systemName === "MRN") ?? patient.identifiers[0];
  const age = deriveAge(patient.birthDate);

  return (
    <header className="patient-header">
      <div className="id-line">
        <div>
          <h1 className="id-name">{name || patient.id}</h1>
          <div className="id-facts">
            <span>{patient.gender ?? <span className="unknown-value">sex not recorded</span>}</span>
            {age !== null ? (
              <>
                <span className="sep">·</span>
                <strong>{age}y</strong>
              </>
            ) : null}
            <span className="sep">·</span>
            <span>
              DOB <strong><PartialDate date={patient.birthDate} /></strong>
            </span>
            {mrn ? (
              <>
                <span className="sep">·</span>
                <span>
                  {mrn.systemName ?? "ID"}{" "}
                  <strong className="id-mrn">{mrn.value}</strong>
                </span>
              </>
            ) : null}
            {patient.withheldIdentifierCount > 0 ? (
              <>
                <span className="sep">·</span>
                <span
                  className="unknown-value"
                  title="A clinical snapshot has no use for a national identifier, so it is withheld by the API rather than masked."
                >
                  {patient.withheldIdentifierCount} identifier withheld
                </span>
              </>
            ) : null}
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {patient.profilesClaimed.length > 0 ? (
            <Badge tone="ok" title={patient.profilesClaimed.join(", ")}>US Core Patient</Badge>
          ) : (
            <Badge tone="unknown" title="This record declares no meta.profile.">
              no profile claim
            </Badge>
          )}
        </div>
      </div>

      <FreshnessStrip meta={meta} />

      <details className="note" style={{ marginTop: 9 }}>
        <summary>Demographics &amp; contact</summary>
        <div className="patient-facts" style={{ marginTop: 4 }}>
          <Fact label="Birth sex (US Core)">
            {patient.usCore.birthsex ?? (
              <span
                className="unknown-value"
                title="us-core-birthsex is must-support in US Core but absent from this record."
              >
                not recorded
              </span>
            )}
          </Fact>
          <Fact label="Race">
            {patient.usCore.raceText ?? patient.usCore.race?.display ?? (
              <span className="unknown-value">not recorded</span>
            )}
          </Fact>
          <Fact label="Ethnicity">
            {patient.usCore.ethnicityText ?? patient.usCore.ethnicity?.display ?? (
              <span className="unknown-value">not recorded</span>
            )}
          </Fact>
          <Fact label="Address">
            {[patient.addressLines.join(", "), patient.city, patient.state, patient.postalCode]
              .filter(Boolean)
              .join(", ") || <span className="unknown-value">not recorded</span>}
          </Fact>
          <Fact label="Contact">
            {patient.telecom.length > 0 ? (
              patient.telecom.map(([system, value]) => `${value} (${system})`).join(", ")
            ) : (
              <span className="unknown-value">not recorded</span>
            )}
          </Fact>
        </div>
      </details>
    </header>
  );
}

/**
 * Three dates that mean three different things.
 *
 * Conflating them is the easy mistake: "data as of" could plausibly be read as
 * any of the three, and a clinician acting on a stale snapshot needs to know
 * which is which. Each is labelled, and the gap since the last real clinical
 * event is stated in days rather than left to arithmetic.
 */
function FreshnessStrip({ meta }: { meta: SnapshotMeta }) {
  const days = meta.daysSinceLatestActivity;
  return (
    <div className="freshness">
      <span className="freshness-item">
        <span className="freshness-label">Record exported</span>
        <span className="freshness-value">{formatDay(meta.bundleTimestamp)}</span>
      </span>
      <span className="freshness-item">
        <span className="freshness-label">Last clinical activity</span>
        <span className="freshness-value">{formatDay(meta.latestClinicalActivity)}</span>
        {days !== null ? <span className="freshness-age">({days} days ago)</span> : null}
      </span>
      <span className="freshness-item">
        <span className="freshness-label">Page rendered</span>
        <span className="freshness-value">{formatInstant(meta.generatedAt)}</span>
      </span>
    </div>
  );
}

const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];

function formatDay(iso: string | null): string {
  if (!iso) return "unknown";
  const [year, month, day] = iso.slice(0, 10).split("-");
  if (!year || !month || !day) return iso;
  return `${day} ${MONTHS[Number(month) - 1] ?? month} ${year}`;
}

function formatInstant(iso: string): string {
  const day = formatDay(iso);
  const time = iso.slice(11, 16);
  return time ? `${day}, ${time} UTC` : day;
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <span className="fact-label">{label}</span>
      <span className="fact-value">{children}</span>
    </div>
  );
}
