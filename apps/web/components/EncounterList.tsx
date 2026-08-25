import {
  CodeLabel,
  Empty,
  FlagBadges,
  PartialDate,
  SectionHead,
  sectionId,
} from "@/components/primitives";
import type { EncounterItem } from "@/lib/types";

const TITLE = "Recent encounters";

export function EncounterList({ encounters }: { encounters: EncounterItem[] }) {
  return (
    <section className="card" aria-labelledby={sectionId(TITLE)}>
      <SectionHead title={TITLE} />
      {encounters.length === 0 ? (
        <Empty>No encounters recorded.</Empty>
      ) : (
        <ul className="rows">
          {encounters.map((encounter) => (
            <li key={encounter.id}>
              <div className="row">
                <div className="row-head">
                  <span className="row-title">
                    {encounter.type ? (
                      <CodeLabel coding={encounter.type} />
                    ) : (
                      <span className="unknown-value">encounter type not recorded</span>
                    )}
                  </span>
                  <FlagBadges flags={encounter.flags} />
                </div>
                <div className="row-meta">
                  <span><PartialDate date={encounter.periodStart} /></span>
                  <span>{encounter.encounterClass?.display ?? "class unknown"}</span>
                  <span>{encounter.status ?? "status unknown"}</span>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
