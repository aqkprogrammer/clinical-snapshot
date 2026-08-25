import { DataQualityPanel } from "@/components/DataQualityPanel";
import { DuplicateEvidence } from "@/components/DuplicateEvidence";
import { ExcludedDrawer } from "@/components/ExcludedDrawer";
import type { DuplicateCandidate, ExcludedItem, Issue } from "@/lib/types";

/**
 * Provenance and record-integrity detail, grouped and folded.
 *
 * None of this is a clinical finding, but all of it is part of an honest
 * account of the record: what was retracted, whether two records were merged,
 * and what the pipeline could not do cleanly. Counts stay visible so the
 * reader knows there is something here; the detail expands on demand.
 */
export function RecordIntegrity({
  excluded,
  excludedNote,
  candidate,
  rationale,
  issues,
  recordLabels = {},
}: {
  excluded: ExcludedItem[];
  excludedNote: string;
  candidate?: DuplicateCandidate;
  rationale: string;
  issues: Issue[];
  recordLabels?: Record<string, string>;
}) {
  return (
    <div id="record-integrity">
      <h2 className="integrity-head">Record integrity &amp; provenance</h2>
      <ExcludedDrawer items={excluded} note={excludedNote} />
      {candidate ? (
        <DuplicateEvidence candidate={candidate} rationale={rationale} labels={recordLabels} />
      ) : null}
      <DataQualityPanel issues={issues} />
    </div>
  );
}
