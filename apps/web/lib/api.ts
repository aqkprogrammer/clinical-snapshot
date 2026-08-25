import type { ExcludedResponse, PatientsResponse, SnapshotResponse } from "./types";

const BASE_URL = process.env.API_BASE_URL ?? "http://localhost:8000";

export class ApiUnavailableError extends Error {}

async function get<T>(path: string): Promise<T> {
  let response: Response;
  try {
    // The snapshot must reflect the bundle on disk on every load, so no caching.
    response = await fetch(`${BASE_URL}${path}`, { cache: "no-store" });
  } catch (cause) {
    throw new ApiUnavailableError(
      `Could not reach the Clinical Snapshot API at ${BASE_URL}. Is the backend running?`,
      { cause },
    );
  }
  if (!response.ok) {
    throw new ApiUnavailableError(
      `API returned ${response.status} for ${path}.`,
    );
  }
  return (await response.json()) as T;
}

export const fetchPatients = () => get<PatientsResponse>("/api/v1/patients");

export const fetchSnapshot = (patientId: string) =>
  get<SnapshotResponse>(`/api/v1/patients/${patientId}/snapshot`);

export const fetchExcluded = (patientId: string) =>
  get<ExcludedResponse>(`/api/v1/patients/${patientId}/excluded`);
