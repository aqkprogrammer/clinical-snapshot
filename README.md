# Clinical Snapshot

A one-page clinical summary built from a deliberately messy FHIR R4 bundle.

The interesting problem here is not rendering a patient summary. It is deciding
what the data actually supports saying, and making the gap between "recorded",
"unknown", and "retracted" visible instead of smoothing it over.

---

## Running it

```bash
docker compose up --build      # http://localhost:3000
```

Or locally, in two terminals:

```bash
make install
make api      # http://localhost:8000  (docs at /docs)
make web      # http://localhost:3000
```

```bash
make check    # 153 backend tests + ruff + mypy --strict + tsc --noEmit
```

Requires Docker, or Python 3.11+ and Node 20+. The application makes no
outbound network calls and needs no API key.

---

## What the bundle contains

17 resources, 2 Patient records, and at least eleven distinct data-quality
problems. Six were named in the brief; the rest were not:

| | Problem | Where |
|---|---|---|
| ✔ | Two Patient records with overlapping, partly conflicting fields | `patient-001`, `patient-002` |
| ✔ | Four resources retracted at source | via **two different** FHIR mechanisms |
| ✔ | Four codes with no display | ICD-10-CM, LOINC, RxNorm, SNOMED CT |
| ✔ | Two references to resources not in the bundle | `encounter-099`, `practitioner-999` |
| ✔ | Six year-precision dates among full timestamps | across five resource types |
| ✔ | US Core extensions | race + ethnicity on `patient-001` only |
| ✚ | **A SNOMED-declared code that is LOINC-shaped** | `allergyintolerance-001` |
| ✚ | **`Bundle.total` on a `collection` bundle** — violates invariant `bdl-1` | bundle |
| ✚ | **`urn:uuid:` fullUrls whose payloads are not UUIDs** | all 17 entries |
| ✚ | **Relative references against URN fullUrls** — strictly, nothing resolves | all 20 references |
| ✚ | **No `Condition.category` on any condition** | so this is not a problem list |
| ✚ | No Provenance, no `meta.versionId` anywhere | record recency unknowable |

---

## The four decisions that mattered

### 1. The two Patient records are not merged

They share a surname, a first name, a sex, a normalised address and a birth
year. Merging them is the obvious move and it is wrong, because the source
says the opposite:

- The two MRNs are **different values in the same assigning system**. One system
  issuing two identifiers is that system asserting two identities.
- **Neither record carries `Patient.link`.** FHIR provides `replaced-by`,
  `replaces`, `refer` and `seealso` precisely so a source can say "same person".
  This source declined to.
- The only high-entropy identifier (an SSN) exists on one record only.
- The birth dates agree *only because one is year-precision*. A day-level match
  was never established.
- Same surname at same address is the textbook master-patient-index false
  positive — two relatives in one household. Nothing here excludes it.

So the app scores evidence in both directions and stops. `mergePerformed` is
`false` unless the source asserted a link; a fixture bundle *with* a
`Patient.link` proves the reverse path works.

**But the duplicate record's active medication is still shown.** Hiding it would
be its own safety failure — if the records *are* the same person, omitting an
active order breaks medication reconciliation. It appears in its own attributed
block: *"From MRN-48213-A — a possible duplicate record. Same-person status is
NOT confirmed."* Shown, attributed, never merged, never counted as the subject's.

### 2. Retracted resources are excluded — but not deleted

Four resources are entered-in-error, and they hide behind **two different
fields**:

| Resource | Mechanism |
|---|---|
| `observation-004` — creatinine 14.7 mg/dL | `Observation.status` |
| `encounter-002` | `Encounter.status` |
| `condition-002` — asthma | `Condition.verificationStatus` |
| `allergyintolerance-002` — latex | `AllergyIntolerance.verificationStatus` |

`Condition` and `AllergyIntolerance` have no `status` element at all, so
checking `resource.status` catches only half of them. Both also carry a
non-active `clinicalStatus`, so a clinicalStatus-first rule would hide them
*coincidentally*, report the wrong reason, and still leave the retracted
creatinine and the phantom encounter on screen. **`verificationStatus` is
therefore evaluated before `clinicalStatus`**, and the mechanism is recorded.

They go to a labelled, collapsed drawer rather than being dropped: a snapshot
that silently discards a corrected lab result looks identical to one where the
test was never done, and the fact that a retraction happened is itself
clinically meaningful.

The retracted creatinine's **value** is withheld even there. 14.7 mg/dL is
roughly ten times normal; read alone it implies renal failure in a patient on
an ACE inhibitor. The resource, its code and the retraction are shown; the
number is not. (`CLINICAL_SNAPSHOT_WITHHOLD_EXCLUDED_OBSERVATION_VALUES=false`
to change that.)

### 3. Missing displays stay missing

`E11.9`, `4548-4`, `849574` and `91936005` have no display in the bundle. I know
what several of them are. The application does not say so.

Displays resolve from exactly one auditable source: a curated map of CodeSystems
defined **by the FHIR specification itself** (`condition-ver-status`,
`v3-ActCode`, …), each entry citing where it came from. SNOMED CT, LOINC, RxNorm
and ICD-10-CM are out of scope — they are large, licensed and separately
versioned, and we have no terminology server. Those render as
*"ICD-10-CM E11.9 — display unavailable"*.

This matters more than it looks. `allergyintolerance-003` carries SNOMED
`91936005` with no display, while `allergyintolerance-001` carries the display
"Penicillin" on a code that **is not a well-formed SNOMED identifier** (`7980-2`
is hyphenated — LOINC-shaped). Resolving `91936005` from memory could present
two entries that are one concept, or equate a *confirmed high-criticality*
allergy with an *unconfirmed unable-to-assess* one. So: no invented displays, and
**no de-duplication of allergies at all**, because de-duplication means trusting
codes and one of these two does not validate.

The "Penicillin" label is kept — discarding a high-criticality allergy's name is
its own harm — but marked `code / system mismatch` and barred from any coded
logic (`usableForCodedLogic: false`).

### 4. Partial dates keep their precision

`"2019"` is a valid FHIR `dateTime`. The reflexive fix — pad it to `2019-01-01`
so `fromisoformat` stops raising — fabricates a January 1st onset for a
diabetes-coded condition, and would silently affect five other values.

`PartialDate` carries its own precision and deliberately exposes **no** method
returning a padded date. Sorting uses interval bounds that never reach the
payload. The UI renders *"2019 (year only)"*. A safety test asserts that every
date string in the response appears **verbatim** in the source bundle.

Comparing dates uses the same idea: `1958-03-12` and `1958` are compared as the
intervals they denote, so the result is *consistent*, never *equal*.

---

## Architecture

```
data/*.json
   │
   ├─ 1  load & parse ......... lenient Pydantic R4 subset; a bad resource
   │                            degrades itself, never the bundle
   ├─ 2  index & resolve ...... documented 3-step reference policy
   ├─ 3  identity ............. evidence, not a merge
   ├─ 4  safety classify ...... CURRENT | HISTORICAL | EXCLUDED | NEEDS_REVIEW
   ├─ 5  terminology .......... curated map only; miss → null
   ├─ 6  temporal ............. precision preserved
   └─ 7  assemble ............. one destination per resource + issue log
                   │
        FastAPI ───┴─── Next.js (App Router, server components)
```

`apps/api/src/clinical_snapshot/domain/` is pure and I/O-free, which is what
makes the safety properties cheap to test exhaustively. `fhir/models.py` models
what the source *sent*; `schemas/responses.py` models what we are willing to
*say*. Keeping them apart is what stops a raw FHIR field reaching the client
without passing through classification.

### Reference resolution

Every `fullUrl` is a URN (`urn:uuid:patient-001`) while every reference is
relative (`Patient/patient-001`). FHIR resolves a relative reference against the
base set by `fullUrl` — and a `urn:` URI establishes no base. **Read strictly,
none of the 20 references in this bundle resolve.**

Refusing them all would be correct and useless. Resolving them silently would
hide a real defect. So: exact `fullUrl` match, then `ResourceType/id` fallback
(which raises `BDL_REFERENCE_SCHEME_MISMATCH` once at bundle level), then an
unresolved *object* — never `None`. "No encounter recorded" and "the encounter
is missing" are different clinical statements and reach the UI as different
things.

### API

| Endpoint | Purpose |
|---|---|
| `GET /health` | liveness + bundle status |
| `GET /api/v1/patients` | every Patient record + duplicate candidates with evidence |
| `GET /api/v1/patients/{id}/snapshot` | the clinical snapshot, scoped to one record |
| `GET /api/v1/patients/{id}/excluded` | retracted resources, separately |
| `GET /api/v1/patients/{id}/data-quality` | the full typed issue log |

Retracted resources are on their own endpoint so they cannot be rendered beside
clinical sections by accident. Errors are RFC 7807 `application/problem+json`.
OpenAPI at `/docs`.

---

## Testing

153 backend tests. The ones that matter are in `apps/api/tests/safety/`, which
asserts properties that must hold for **any** bundle, against the serialized
HTTP payload rather than domain objects:

- no retracted id reaches a clinical section — and all four **are** reported
- the value `14.7` is unreachable from every endpoint
- every display traces to the source or the curated map; unresolved stays `null`
- every rendered date string appears verbatim in the source
- every unattributed clinical item belongs to the snapshot's subject
- no merge without `Patient.link` — with a fixture proving the reverse
- every bundle entry is accounted for across all sections (nothing vanishes)
- `codeSystemMismatch` always implies `usableForCodedLogic: false`

Four adversarial fixtures: source-asserted link, fully-retracted bundle,
month-precision dates, empty bundle.

---

## Tradeoffs accepted under the time cap

- **The curated terminology map is small.** Correctness and auditability over
  coverage. A real ValueSet/`$lookup` integration slots in behind
  `TerminologyService` without touching callers.
- **No frontend test suite.** The uncertainty logic lives in
  `components/primitives/`, and the backend contract is covered by the safety
  suite. Component tests for those four primitives are the first thing I would
  add.
- **Single bundle, configured by path.** Multi-scenario support is a config
  change, not an abstraction.
- **`_shorten` for unknown identifier systems** turns
  `http://centaurihealth.example.org/mrn` into `MRN` for display. A shortening of
  what the source said, not an interpretation; the full URI stays in the payload.
- **`Observation` routing uses a two-blocker rule** — unnameable *and*
  unclassifiable goes to needs-review. One blocker alone still renders, with the
  caveat attached. That threshold is a judgement call.
- **No auth, no persistence, no pagination.** Out of scope for a read-only
  single-bundle viewer.

## With more time

1. Component tests for the four uncertainty primitives, plus a visual
   regression test on the snapshot page.
2. A real terminology service behind `TerminologyService`, with the curated map
   as an offline fallback.
3. Let a reviewer *act* on the duplicate candidate — record a steward decision
   and persist it as a `Patient.link`, which is the only thing that should ever
   authorise a merge.
4. Per-resource `Provenance` display once a bundle supplies it.
5. Widen the safety suite into property-based tests over generated bundles
   (Hypothesis) rather than four hand-built fixtures.

See `docs/DECISIONS.md` for the full rule tables and the complete identity
evidence analysis, and `AI_USAGE.md` for how the AI assistant was used.
