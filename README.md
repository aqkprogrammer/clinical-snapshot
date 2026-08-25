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
make check    # 360 backend + 75 frontend tests, ruff, mypy --strict, tsc --noEmit
make test     # backend only        make test-web  # frontend only
make lint     # ruff                make typecheck # mypy + tsc
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
makes the safety properties cheap to test exhaustively. Within it, `views.py`
holds the shapes we are willing to render, `snapshot.py` the read model
(`Snapshot` + `NormalizationResult`), `renderability.py` the rule for whether an
Observation can be identified at all, and `assembler.py` the construction. `fhir/models.py` models
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
| `GET /api/v1/health` | liveness + bundle status (`/health` is an unversioned alias for the container health check) |
| `GET /api/v1/patients` | every Patient record + duplicate candidates with evidence |
| `GET /api/v1/patients/{id}/snapshot` | the clinical snapshot, scoped to one record |
| `GET /api/v1/patients/{id}/excluded` | retracted resources, separately |
| `GET /api/v1/patients/{id}/data-quality` | the full typed issue log |

Every error is `application/problem+json` — including 422s from path validation
and anything unhandled. A corrupt or missing bundle is a 503 whose body says the
bundle could not be parsed but does not disclose the path; the specifics go to
the log. `/api/v1/health` stays 200 and reports `degraded`, because a liveness
probe that fails on a bad bundle stops the stack coming up at all instead of
letting it come up and say what is wrong — readiness should key on
`bundleLoaded`.

Retracted resources are on their own endpoint so they cannot be rendered beside
clinical sections by accident. Errors are RFC 7807 `application/problem+json`.
OpenAPI at `/docs`.

Every response is an envelope of `meta` (provenance and staleness), `data`, and
`issues`. A representative fragment:

```json
{
  "meta": {
    "patientId": "patient-001",
    "bundleTimestamp": "2026-06-01T09:00:00Z",
    "latestClinicalActivity": "2025-11-04T15:00:00Z",
    "daysSinceLatestActivity": 293,
    "scopeNote": "Scoped to Patient/patient-001. No Patient records were merged."
  },
  "data": {
    "conditionsCurrent": [{
      "id": "condition-003",
      "code": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm", "code": "E11.9",
        "display": null, "displayStatus": "unresolved",
        "systemName": "ICD-10-CM", "displaySource": "unavailable",
        "usableForCodedLogic": true
      },
      "onset": { "value": "2019", "precision": "year" },
      "encounter": {
        "reference": "Encounter/encounter-099", "resolved": false,
        "reason": "REFERENCE_TARGET_NOT_IN_BUNDLE"
      },
      "categoryDeclared": false,
      "provenance": { "resourceId": "condition-003", "admittedBy": "RULE_CONDITION_CURRENT" }
    }]
  },
  "issues": [
    { "code": "TERMINOLOGY_DISPLAY_MISSING", "severity": "medium",
      "message": "No display available for ICD-10-CM code 'E11.9'. Rendered without a human-readable label rather than guessing one." }
  ]
}
```

Note what the shape forces: `display: null` beside `displayStatus: "unresolved"`
means a consumer cannot render a name without deciding what to do about its
absence, and `onset` cannot be formatted without acknowledging its precision.

---

## Security and privacy

The data is synthetic; the handling is what's being assessed.

- **The SSN is withheld entirely, not masked.** A clinical snapshot has no use
  for a national identifier. The MRN is retained because the duplicate-record
  warning has to name the other record, and `withheldIdentifierCount` keeps the
  omission visible rather than making it look like absent data.
- **Identity evidence never quotes a strong identifier's value** — the evidence
  is that two records matched, not what the identifier was.
- **No PHI in logs.** Structured JSON logging records counts and the requested
  patient id only, with a forbidden-key filter as a backstop. Resource bodies
  are never logged at any level.
- **No raw FHIR leaves the backend.** `fhir/models.py` models what the source
  sent; `schemas/responses.py` models what we are willing to say. Nothing
  crosses without passing through classification.
- **Secrets.** `.gitignore` was written before `git init`, so `.env` has never
  existed in history — verified with `git log --all --diff-filter=A`. The key it
  holds funds the coding assistant, not the application: **the app makes no
  outbound network calls and needs no API key to run.**
- **CORS** is an explicit two-origin localhost allowlist with `GET` only and no
  credentials — never a wildcard.
- **Both containers run unprivileged** — `snapshot` (uid 10001) and `node`.

- **Path parameters are validated against the FHIR `id` charset**
  (`[A-Za-z0-9\-.]{1,64}`), so anything else is rejected as 422 before a handler
  runs — keeping unvalidated input out of both the log line and the 404 body.
  The 422 names the field that failed, never the value.

**Known gaps, deliberately out of scope:** no authentication, authorization or
rate limiting — any caller can read any patient. No security headers
(`X-Content-Type-Options`, CSP). These are the first things to fix before this
went anywhere real.

## Testing

360 backend and 75 frontend tests. The ones that matter are in `apps/api/tests/safety/`, which
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

The frontend suite concentrates on `components/primitives/` — every place the UI
could imply more confidence than the data supports goes through one of four
components, so those are asserted directly: a year-only date never widens, an
unresolved code never acquires a name *and* never falls back to the bare code
styled as one, a mismatched code keeps its label but carries the warning, and an
unresolved reference reads differently from an absent one. Section tests assert
*separation*: stopped medications never share a list with active ones, a
duplicate record's medication only ever appears inside an attributed block, and
no observation row renders an abnormal indicator.

Two of these tests earned their place by catching real regressions during the
build — see `AI_USAGE.md`.

---

## Tradeoffs accepted under the time cap

- **The curated terminology map is small.** Correctness and auditability over
  coverage. A real ValueSet/`$lookup` integration slots in behind
  `TerminologyService` without touching callers.
- **`/excluded` and `/data-quality` re-run the pipeline** rather than deriving
  from one `NormalizationResult`, and use `build()` rather than `normalize()`.
- **`domain/assembler.py` is still ~1,090 lines.** It now does one job rather
  than four, and its longest function is 57 lines, but the ~15 `_build_*` view
  constructors would sit comfortably behind their own `ViewBuilder`.
- **Accessibility beyond focus, boundaries and contrast.** Sections are not
  exposed as landmarks and clinical rows are `<div>`s rather than lists, so a
  screen-reader user gets no item count. Listed in full in the project history.
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

1. Fix the items above: split `snapshot.py`, single-pass the endpoints, and work
   through the remaining accessibility findings.
2. A real terminology service behind `TerminologyService`, with the curated map
   as an offline fallback.
3. Let a reviewer *act* on the duplicate candidate — record a steward decision
   and persist it as a `Patient.link`, which is the only thing that should ever
   authorise a merge.
4. Per-resource `Provenance` display once a bundle supplies it.
5. Widen the safety suite into property-based tests over generated bundles
   (Hypothesis) rather than four hand-built fixtures.

See `docs/DECISIONS.md` for the full rule tables, the complete identity evidence
analysis, and a list of known open items carried deliberately. `AI_USAGE.md`
covers how the AI assistant was directed and, more usefully, the ten places its
output was corrected or rejected.
