import { AllergyList } from "@/components/AllergyList";
import { Banners } from "@/components/Banners";
import { ConditionList } from "@/components/ConditionList";
import { DataQualityPanel } from "@/components/DataQualityPanel";
import { DuplicateEvidence } from "@/components/DuplicateEvidence";
import { EncounterList } from "@/components/EncounterList";
import { ExcludedDrawer } from "@/components/ExcludedDrawer";
import { MedicationList } from "@/components/MedicationList";
import { NeedsReviewList } from "@/components/NeedsReviewList";
import { ObservationList } from "@/components/ObservationList";
import { PatientHeader } from "@/components/PatientHeader";
import { ApiUnavailableError, fetchExcluded, fetchPatients, fetchSnapshot } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function Page({
  searchParams,
}: {
  searchParams: Promise<{ patient?: string }>;
}) {
  const { patient: requested } = await searchParams;

  try {
    const patients = await fetchPatients();
    const available = patients.data.patients.map((p) => p.id);
    if (available.length === 0) {
      return (
        <main className="page">
          <div className="fatal">
            <h1>No Patient resources</h1>
            <p>The bundle contains no Patient resource, so there is nothing to display.</p>
          </div>
        </main>
      );
    }

    const patientId =
      requested && available.includes(requested) ? requested : (available[0] as string);
    const [snapshot, excluded] = await Promise.all([
      fetchSnapshot(patientId),
      fetchExcluded(patientId),
    ]);
    const { data, meta, issues } = snapshot;
    const candidate = data.identity.candidates.find((c) => c.memberIds.includes(patientId));

    return (
      <main className="page">
        {available.length > 1 ? (
          <nav className="small muted" style={{ marginBottom: 12 }}>
            Patient records in this bundle:{" "}
            {patients.data.patients.map((p) => (
              <a
                key={p.id}
                href={`/?patient=${p.id}`}
                style={{
                  marginRight: 10,
                  fontWeight: p.id === patientId ? 700 : 400,
                  color: p.id === patientId ? "var(--accent)" : "var(--muted)",
                }}
              >
                {p.display} ({p.identifiers[0]?.value ?? p.id})
              </a>
            ))}
            <span title={meta.scopeNote}> · records are never merged</span>
          </nav>
        ) : null}

        <PatientHeader patient={data.patient} meta={meta} />
        <Banners warnings={data.warnings} />

        <div className="grid">
          <div>
            <ConditionList
              current={data.conditionsCurrent}
              historical={data.conditionsHistorical}
              categoryDeclared={data.conditionsCategoryDeclared}
            />
            <MedicationList
              active={data.medicationsActive}
              historical={data.medicationsHistorical}
            />
            <EncounterList encounters={data.encounters} />
          </div>
          <div>
            <AllergyList current={data.allergiesCurrent} historical={data.allergiesHistorical} />
            <ObservationList
              title="Vital signs"
              observations={data.vitalSigns}
              emptyText="No vital signs recorded."
            />
            <ObservationList
              title="Other observations"
              observations={data.otherObservations}
              emptyText="No other observations recorded."
            />
            <NeedsReviewList items={data.needsReview} />
          </div>
        </div>

        {candidate ? (
          <DuplicateEvidence
            candidate={candidate}
            rationale={data.identity.primarySelectionRationale}
          />
        ) : null}
        <ExcludedDrawer items={excluded.data.excluded} note={excluded.data.note} />
        <DataQualityPanel issues={issues} />

        <footer className="small muted" style={{ marginTop: 26, textAlign: "center" }}>
          Bundle <span className="mono">{meta.bundleId}</span> · generated{" "}
          {meta.generatedAt.slice(0, 19).replace("T", " ")} UTC ·{" "}
          {meta.daysSinceLatestActivity} days since last clinical activity
        </footer>
      </main>
    );
  } catch (error) {
    if (error instanceof ApiUnavailableError) {
      return (
        <main className="page">
          <div className="fatal">
            <h1>Cannot reach the API</h1>
            <p>{error.message}</p>
            <p className="small">
              Start it with <code>make api</code>, or run the whole stack with{" "}
              <code>docker compose up</code>.
            </p>
          </div>
        </main>
      );
    }
    throw error;
  }
}
