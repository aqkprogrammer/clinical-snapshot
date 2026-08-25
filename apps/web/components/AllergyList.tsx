import {
  Badge,
  CodeCaveat,
  CodeLabel,
  Empty,
  FlagBadges,
  InfoNote,
  PartialDate,
  SectionHead,
  sectionId,
} from "@/components/primitives";
import type { AllergyItem } from "@/lib/types";

const TITLE = "Allergies & intolerances";

export function AllergyList({ current, historical }: {
  current: AllergyItem[];
  historical: AllergyItem[];
}) {
  const hasMismatch = current.some((allergy) => allergy.code.codeSystemMismatch);

  return (
    <section className="card" aria-labelledby={sectionId(TITLE)}>
      <SectionHead
        title={TITLE}
        note={
          hasMismatch ? (
            <InfoNote label="entries not de-duplicated">
              One record carries a code that does not validate against the code system it
              declares. Entries are <strong>not</strong> merged or de-duplicated, because
              doing so would mean trusting those codes.
            </InfoNote>
          ) : undefined
        }
      />

      {current.length === 0 ? (
        <Empty>
          No active allergies recorded. This is not the same as &ldquo;no known allergies&rdquo;.
        </Empty>
      ) : (
        <ul className="rows">
          {current.map((allergy) => (
            <li key={allergy.id}>
              <Row allergy={allergy} />
            </li>
          ))}
        </ul>
      )}

      {historical.length > 0 ? (
        <div className="subordinate">
          <div className="subordinate-title">Resolved / inactive</div>
          <ul className="rows">
            {historical.map((allergy) => (
              <li key={allergy.id}>
                <Row allergy={allergy} />
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

/**
 * Severity leads.
 *
 * Criticality and verification are the two things that decide how much weight
 * to give an entry, so they sit immediately beside the substance name rather
 * than in the metadata line below it.
 */
function Row({ allergy }: { allergy: AllergyItem }) {
  const verification = allergy.verificationStatus?.display?.toLowerCase();
  return (
    <div className="row">
      <div className="row-head">
        <span className="row-title"><CodeLabel coding={allergy.code} /></span>
        {allergy.criticality === "high" ? (
          <Badge tone="danger" title="High criticality as recorded by the source.">
            high risk
          </Badge>
        ) : allergy.criticality ? (
          <Badge tone="unknown" title="The source could not assess criticality.">
            {allergy.criticality.replace(/-/g, " ")}
          </Badge>
        ) : (
          <Badge tone="unknown" title="The source recorded no criticality.">
            criticality not recorded
          </Badge>
        )}
        {/*
          * The classifier's flags are authoritative and always render. The
          * "confirmed" badge is shown only when there is no flag to contradict
          * it, so an entry is never marked both confirmed and uncertain.
          */}
        <FlagBadges flags={allergy.flags} />
        {allergy.flags.length === 0 && verification === "confirmed" ? (
          <Badge tone="ok">confirmed</Badge>
        ) : null}
        {allergy.flags.length === 0 && verification && verification !== "confirmed" ? (
          <Badge tone="warn">{verification}</Badge>
        ) : null}
      </div>
      <div className="row-meta">
        <span>Recorded <PartialDate date={allergy.recordedDate} /></span>
        <span>{allergy.clinicalStatus?.display ?? "status unknown"}</span>
      </div>
      <CodeCaveat coding={allergy.code} />
    </div>
  );
}
