import { CodeLabel, Empty, FlagBadges, PartialDate } from "@/components/primitives";
import type { EncounterItem } from "@/lib/types";

export function EncounterList({ encounters }: { encounters: EncounterItem[] }) {
  return (
    <section className="card">
      <h2>Recent encounters</h2>
      {encounters.length === 0 ? (
        <Empty>No encounters recorded.</Empty>
      ) : (
        encounters.map((encounter) => (
          <div key={encounter.id} className="row">
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
              <span>Status: {encounter.status ?? "unknown"}</span>
            </div>
          </div>
        ))
      )}
    </section>
  );
}
