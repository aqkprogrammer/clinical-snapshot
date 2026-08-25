import { AllergyList } from "@/components/AllergyList";
import { Banners, type DuplicateContext } from "@/components/Banners";
import { ConditionList } from "@/components/ConditionList";
import { EncounterList } from "@/components/EncounterList";
import { GlanceStrip } from "@/components/GlanceStrip";
import { MedicationList } from "@/components/MedicationList";
import { ObservationList } from "@/components/ObservationList";
import { OtherResults } from "@/components/OtherResults";
import { PatientHeader } from "@/components/PatientHeader";
import { RecordIntegrity } from "@/components/RecordIntegrity";
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

    // A record number a clinician recognises, taken from the attribution the
    // backend already supplies -- never a database id.
    const attributed = data.medicationsActive.filter((m) => m.attribution);
    const duplicate: DuplicateContext | undefined = candidate
      ? {
          label: attributed[0]?.attribution?.patientLabel ?? "another record",
          medicationCount: attributed.length,
        }
      : undefined;

    // Record ids are how the API addresses patients; a clinician reads MRNs.
    const recordLabels = Object.fromEntries(
      patients.data.patients.map((p) => [p.id, p.identifiers[0]?.value ?? p.id]),
    );

    return (
      <>
        <a href="#clinical" className="skip-link">Skip to clinical content</a>
        <main className="page">
          <PatientHeader patient={data.patient} meta={meta} />
          <Banners warnings={data.warnings} duplicate={duplicate} />
          <GlanceStrip data={data} issueCount={issues.length} />

          {/*
            * Two columns, ordered by how a clinician scans: allergies and
            * medications on the left (what could harm the patient, what they
            * are taking), problems and vitals on the right. Secondary results
            * fill the right column so the two sides finish at similar heights.
            */}
          <div id="clinical" className="grid">
            <div>
              <AllergyList
                current={data.allergiesCurrent}
                historical={data.allergiesHistorical}
              />
              <MedicationList
                active={data.medicationsActive}
                historical={data.medicationsHistorical}
              />
            </div>
            <div>
              <ConditionList
                current={data.conditionsCurrent}
                historical={data.conditionsHistorical}
                categoryDeclared={data.conditionsCategoryDeclared}
              />
              <ObservationList
                title="Vital signs"
                observations={data.vitalSigns}
                emptyText="No vital signs recorded."
              />
              <EncounterList encounters={data.encounters} />
              <OtherResults
                observations={data.otherObservations}
                needsReview={data.needsReview}
              />
            </div>
          </div>

          <RecordIntegrity
            excluded={excluded.data.excluded}
            excludedNote={excluded.data.note}
            candidate={candidate}
            rationale={data.identity.primarySelectionRationale}
            issues={issues}
            recordLabels={recordLabels}
          />

          {available.length > 1 ? (
            <nav className="record-switch" aria-label="Patient records in this bundle">
              <span className="muted">Records in this bundle:</span>
              {patients.data.patients.map((p) => (
                <a
                  key={p.id}
                  href={`/?patient=${p.id}`}
                  aria-current={p.id === patientId ? "page" : undefined}
                  className={p.id === patientId ? "current" : undefined}
                >
                  {p.identifiers[0]?.value ?? p.id}
                </a>
              ))}
              <span className="muted" title={meta.scopeNote}>· never merged</span>
            </nav>
          ) : null}

          <footer className="small muted" style={{ marginTop: 18, textAlign: "center" }}>
            Bundle <span className="mono">{meta.bundleId}</span>
          </footer>
        </main>
      </>
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
