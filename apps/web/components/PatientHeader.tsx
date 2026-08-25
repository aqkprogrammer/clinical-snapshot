import { Badge, PartialDate } from "@/components/primitives";
import type { PatientDetail, SnapshotMeta } from "@/lib/types";

export function PatientHeader({ patient, meta }: { patient: PatientDetail; meta: SnapshotMeta }) {
  const name = [...patient.givenNames, patient.familyName].filter(Boolean).join(" ");
  const address = [
    patient.addressLines.join(", "),
    patient.city,
    patient.state,
    patient.postalCode,
  ]
    .filter(Boolean)
    .join(", ");

  return (
    <header className="patient-header">
      <div style={{ display: "flex", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
        <div>
          <h1>{name || patient.id}</h1>
          <div className="small muted" style={{ marginTop: 4 }}>
            {patient.identifiers.map((identifier) => (
              <span key={`${identifier.system}-${identifier.value}`} style={{ marginRight: 14 }}>
                {identifier.systemName}: <span className="mono">{identifier.value}</span>
                {identifier.masked ? (
                  <>
                    {" "}
                    <Badge tone="neutral" title="Masked at source; shown as received.">masked</Badge>
                  </>
                ) : null}
              </span>
            ))}
            {patient.withheldIdentifierCount > 0 ? (
              <span
                title="A clinical snapshot has no use for a national identifier, so it is withheld by the API rather than masked."
                className="unknown-value"
              >
                {patient.withheldIdentifierCount} identifier withheld
              </span>
            ) : null}
          </div>
        </div>
        <div className="small muted" style={{ textAlign: "right", minWidth: 210 }}>
          <div>
            Data as of{" "}
            <strong>{meta.bundleTimestamp?.slice(0, 10) ?? "unknown"}</strong>
          </div>
          <div>
            Last clinical activity{" "}
            <strong>{meta.latestClinicalActivity?.slice(0, 10) ?? "unknown"}</strong>
          </div>
          {patient.profilesClaimed.length > 0 ? (
            <div style={{ marginTop: 5 }}>
              <Badge tone="ok" title={patient.profilesClaimed.join(", ")}>US Core Patient</Badge>
            </div>
          ) : (
            <div style={{ marginTop: 5 }}>
              <Badge tone="unknown" title="This record declares no meta.profile.">
                no profile claim
              </Badge>
            </div>
          )}
        </div>
      </div>

      <div className="patient-facts">
        <Fact label="Date of birth">
          <PartialDate date={patient.birthDate} />
        </Fact>
        <Fact label="Sex">{patient.gender ?? <span className="unknown-value">not recorded</span>}</Fact>
        <Fact label="Birth sex (US Core)">
          {patient.usCore.birthsex ?? (
            <span className="unknown-value" title="us-core-birthsex is must-support in US Core but absent here.">
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
        <Fact label="Address">{address || <span className="unknown-value">not recorded</span>}</Fact>
        <Fact label="Contact">
          {patient.telecom.length > 0
            ? patient.telecom.map(([system, value]) => `${value} (${system})`).join(", ")
            : <span className="unknown-value">not recorded</span>}
        </Fact>
      </div>
    </header>
  );
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <span className="fact-label">{label}</span>
      <span className="fact-value">{children}</span>
    </div>
  );
}
