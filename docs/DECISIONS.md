# Decisions

The rule tables and reasoning behind the normalization layer. The README has
the summary; this has the detail and the edge cases.

---

## 1. Clinical safety classification

Every non-Patient resource is placed in exactly one disposition.

| Disposition | Meaning |
|---|---|
| `CURRENT` | Safe to present as a current clinical fact |
| `HISTORICAL` | Real, non-retracted, no longer current. Shown, never beside current facts |
| `EXCLUDED` | Retracted at source. Never a clinical fact; visible only in the labelled drawer |
| `NEEDS_REVIEW` | Too incomplete or ambiguous to place. Shown in its own section rather than guessed into another |

### The precedence that matters

`Condition` and `AllergyIntolerance` have **no `status` element**. They retract
via `verificationStatus`. `Observation` and `Encounter` retract via `status`. An
implementation that checks `resource.status` catches half the retractions in this
bundle.

Worse: `condition-002` is *also* `clinicalStatus: inactive` and
`allergyintolerance-002` is *also* `clinicalStatus: resolved`. A
`clinicalStatus`-first rule hides both — **for the wrong reason**, reporting the
wrong mechanism — and still leaves the retracted creatinine and the phantom
encounter on screen.

So `verificationStatus` is evaluated **before** `clinicalStatus`, and the field
that carried the retraction is recorded and displayed.

### Full rule table

| Resource | Field | Rule |
|---|---|---|
| Condition | `verificationStatus` → `clinicalStatus` | `entered-in-error`/`refuted` → **EXCLUDED**; `active`/`recurrence`/`relapse` → CURRENT; `inactive`/`remission`/`resolved` → HISTORICAL; `unconfirmed`/`provisional`/`differential` → CURRENT + `unconfirmed` flag; absent → NEEDS_REVIEW |
| AllergyIntolerance | `verificationStatus` → `clinicalStatus` | Same precedence. `active` → CURRENT; `inactive`/`resolved` → HISTORICAL |
| Observation | `status` | `entered-in-error` → **EXCLUDED**; `final`/`amended`/`corrected` → CURRENT; `preliminary`/`registered`/`cancelled`/`unknown` → NEEDS_REVIEW |
| Encounter | `status` | `entered-in-error` → **EXCLUDED**; `finished` → HISTORICAL; `in-progress`/`arrived`/`triaged`/`onleave` → CURRENT; `cancelled` → HISTORICAL + `cancelled` flag |
| MedicationRequest | `status` | `entered-in-error` → **EXCLUDED**; `active` → CURRENT; `on-hold` → CURRENT + flag; `stopped`/`completed`/`cancelled`/`ended`/`expired` → HISTORICAL; `draft`/`unknown` → NEEDS_REVIEW |

### Judgement calls inside the table

**An unconfirmed allergy still displays.** `allergyintolerance-003` is
`active` + `unconfirmed` with criticality `unable-to-assess` and no resolvable
substance name. Suppressing it risks an exposure; the caveat rides along
instead.

**A stopped medication is HISTORICAL, not EXCLUDED.** `medicationrequest-002`
(Metformin, stopped) is a genuine fact about the patient's history. Suppressing
it alongside the retracted resources would lose real clinical information. It
gets its own section under a heading that says *"do not treat as current."*

**A cancelled encounter is HISTORICAL, flagged.** It is a real record of
something that did not happen — not retracted, so not excluded, but flagged so
it never reads as an attended visit.

**Excluded is not deleted.** Retracted resources go to a labelled, collapsed
drawer. A snapshot that silently discards a corrected lab result is
indistinguishable from one where the test was never done, and the fact that a
retraction occurred is itself clinically meaningful.

**The retracted creatinine's value is withheld even in the drawer.**
14.7 mg/dL is roughly ten times normal. Read alone it implies renal failure in a
patient on an ACE inhibitor (lisinopril, `medicationrequest-001`). The resource,
its code, and the fact of retraction are shown; the number is not. Configurable
via `CLINICAL_SNAPSHOT_WITHHOLD_EXCLUDED_OBSERVATION_VALUES=false`.

---

## 2. Patient reconciliation

**Determination: `UNRECONCILED`. Confidence: `CONFLICTED`. No merge.**

### Evidence for

| Signal | Strength |
|---|---|
| `family-name-match` — Whitfield | weak |
| `given-name-match` — Dorothy | weak |
| `gender-match` — female | very weak (~50% prior) |
| `birthdate-consistent-at-reduced-precision` — `1958-03-12` vs `1958` | weak |
| `address-match-normalised` — 482 Larkspur Lane ≡ Ln | moderate |
| `identifier-shared-root` — MRN-48213 / MRN-48213-A | **suggestive only** |

### Evidence against, or blocking confirmation

| Signal | Strength |
|---|---|
| `distinct-identifier-same-system` — two values from one assigning system | **strong** |
| `no-patient-link` — FHIR offers `replaced-by`/`replaces`/`refer`/`seealso`; the source used none | **strong** |
| `shared-address-relative-risk` — same surname + same address is the textbook MPI false positive | **strong** |
| `no-corroborating-strong-identifier` — SSN on one record only | blocks confirmation |
| `birthdate-precision-differs` — day-level match never established | blocks confirmation |
| `telecom-disjoint` — no shared number; confirms nothing, refutes nothing | neutral |
| `completeness-asymmetry` — patient-002 has no profile claim, no extensions | weak |

### The policy

Confidence is graded deterministically, and the precedence *is* the policy:

1. A source-asserted `Patient.link` is `CONFIRMED` — **the only merge-authorising state**.
2. **Conflicting strong identifiers outrank every demographic signal.** Two
   records issued different identifiers by the same assigning system are two
   identities as far as that system is concerned, however well the names line up.
3. Only then can a matching high-entropy identifier raise confidence to `PROBABLE`.
4. Demographic agreement alone never exceeds `POSSIBLE`.

Even `PROBABLE` does not merge. Only the source system may assert identity.

### Why the `-A` suffix is not evidence

`MRN-48213-A` *could* mean "duplicate account". It could equally mean an alias
registration, a guarantor account, a merged-from stub, or a different person
assigned a suffixed number. The system defines no semantics for it. Reading
intent into an identifier string is precisely how MPI false positives are made,
so it is scored `suggestive-only` and can never move the determination.

### What is shown instead

The snapshot is scoped to `patient-001` — a **selection of which record to
display**, not a merge. `medicationrequest-003` (active, RxNorm `849574`, no
resolvable name) belongs to `patient-002` and **is shown**, in its own attributed
block: *"From MRN-48213-A — a possible duplicate record. Same-person status is
NOT confirmed."*

Under asymmetric loss this dominates hiding it:

- *If same person:* showing it (attributed) completes medication reconciliation.
  Hiding it omits an active medication — a real harm.
- *If different person:* the provenance label means no clinician mistakes it for
  this patient's drug. Hiding it is merely also-correct.

Three or more overlapping records produce **pairwise** candidates, not a merged
cluster — clustering would assert a transitive identity claim the evidence does
not support.

---

## 3. Terminology

### Scope rule

**In scope:** CodeSystems defined *by the FHIR R4 specification itself* —
`condition-clinical`, `condition-ver-status`, `allergyintolerance-*`,
`observation-category`, `v3-ActCode`. Small, closed, normative, versioned with
FHIR. Resolving `confirmed` → "Confirmed" is reading the published spec.

**Out of scope:** SNOMED CT, LOINC, RxNorm, ICD-10-CM. Large, licensed,
separately versioned. No terminology server is available, so a code from one of
these with no source display resolves to `null` and renders as *"display
unavailable"*.

Every entry in `terminology/displays.yaml` cites its source.

### `displaySource`

| Value | Meaning |
|---|---|
| `fhir` | The bundle supplied the display; passed through unchanged |
| `verified-local-map` | Filled from the curated map; `displaySourceDetail` cites which CodeSystem |
| `unavailable` | No display, and none was inferred |

### Code-shape validation

Codes are structurally validated against the system they declare. `7980-2` is
hyphenated and LOINC-shaped; it is **not** a well-formed SNOMED CT concept
identifier, yet `allergyintolerance-001` declares SNOMED CT and carries the
display "Penicillin".

We cannot tell which of the two fields is wrong, so:
- the display is **kept** — discarding a high-criticality allergy's label is its own harm;
- it is marked `from-source-unvalidated` with a visible `code / system mismatch` badge;
- `usableForCodedLogic` is `false`, barring the code from any grouping, matching or interaction check.

### No allergy de-duplication

`allergyintolerance-003` carries SNOMED `91936005` with no display.
De-duplicating against `allergyintolerance-001` requires trusting both codes, and
one of them does not validate. Collapsing them could present a *confirmed
high-criticality* allergy and an *unconfirmed unable-to-assess* one as
equivalent. So no de-duplication is attempted, and the section says so.

### Multiple codings

FHIR permits several codings as translations of one concept. The first is
rendered; the rest are resolved, retained, and reported. An alternate coding's
display is **never** promoted onto a primary that lacks one — borrowing a label
across code systems is inventing one.

---

## 4. Dates

`PartialDate` carries `value` (the source string, byte for byte) and
`precision` (`year` | `month` | `day` | `instant`). There is deliberately **no
method that returns a padded date**.

| Property | Behaviour |
|---|---|
| `parsed_date` | `None` for year and month precision — every candidate would be invented |
| `parsed_instant` | Only for full timestamps; always timezone-aware |
| `sort_key` | Interval bounds; never reaches the payload |
| `display` | `"2019 (year only)"` — precision is visible, never hidden |

Comparison uses interval overlap, so `1958-03-12` vs `1958` is **consistent**,
never **equal**.

`is_reduced_precision` is a statement about the *format* of the source string,
not a heuristic about its content: `2018-01-01T00:00:00Z` is a full instant that
happens to land on New Year's midnight, and must not be flagged as partial.

Absent and malformed are distinguished — both render nothing, but only one
raises `DATE_INVALID`.

---

## 5. Reference resolution

Every `fullUrl` in this bundle is a URN while every reference is relative. FHIR
resolves a relative reference against the base set by `fullUrl`, and a `urn:`
URI establishes no base. **Read strictly, none of the 20 references resolve.**

Ordered policy:

1. Exact `fullUrl` match.
2. `ResourceType/id` fallback — raises `BDL_REFERENCE_SCHEME_MISMATCH` once at bundle level.
3. No match → an unresolved **result object**, never `None`.

Four outcomes are distinguished — `RESOLVED`, `UNRESOLVED`, `TYPE_MISMATCH`,
`MALFORMED` — because they mean different things to a reader. A type mismatch
withholds the target rather than returning the wrong kind of resource. The
original reference string is preserved in every outcome.

`resolve()` returns `None` **only** when there is no reference at all: "the
source recorded nothing here" is a different clinical statement from "the source
pointed at something missing", and the two render differently.

---

## 6. Indexing

`BundleIndex` never overwrites a duplicate. First occurrence (bundle order)
answers lookups; shadowed copies stay reachable via `candidates()` so a caller
can compare them. Conflicts are returned as data — `DUPLICATE_KEY`,
`DUPLICATE_FULL_URL`, `MISSING_ID` — never raised, never silently resolved.

The layer is **structural only**. It knows `resourceType`, `id`, `fullUrl` and
reference strings, and consults no clinical status: an `entered-in-error`
resource indexes exactly like any other. Safety decisions live in
`domain/safety.py`.

---

## 7. Privacy

The SSN is **withheld entirely**, not masked. A clinical snapshot has no use for
a national identifier. The MRN is retained because the duplicate-record warning
has to name the other record. `withheldIdentifierCount` keeps the omission
visible rather than making it look like absent data.

Identity evidence never quotes a strong identifier's value — the evidence is
that they matched, not what they are.

Logs record counts and the requested patient id only. Resource bodies are never
logged at any level.

---

## 8. Known open items

Carried deliberately, with reasons, rather than fixed silently:

- `/excluded` and `/data-quality` re-run the pipeline via `build()` rather than
  `normalize()`, so they do not populate `unresolved_references`.
- `domain/assembler.py` is ~1,090 lines. It does one job now rather than four,
  and its longest function is 57 lines, but the `_build_*` view constructors
  would sit comfortably behind their own `ViewBuilder`.
- Accessibility: sections are not exposed as landmarks and clinical rows are
  `<div>`s rather than lists, so a screen-reader user gets no item count.

These are recorded in full in the review sections of the project history.

## 9. Robustness

A bad bundle and a bad path parameter are the two remaining sources of input the
application does not control.

**Bad bundle.** `load_bundle` failures are typed — `BundleNotFoundError` for a
missing path, `BundleUnreadableError` for unparseable JSON, a wrong-shaped
document, or an unreadable file. Both surface as 503 `problem+json` with a
generic message; the specifics are logged rather than returned, because a 503
body should not disclose a filesystem path to an unauthenticated caller.
`/api/v1/health` degrades instead of failing.

**Bad path parameter.** `patient_id` is constrained to the FHIR `id` charset,
`[A-Za-z0-9\-.]{1,64}`, so anything else is a 422 raised by the framework before
a handler runs. That closes two things at once: an over-long or injection-shaped
id can no longer reach a structured log line, and the 404 body can safely name
the id it did not find because only safe characters can get that far. The 422
reports the field that failed, never the value.

A catch-all handler backstops both, returning `problem+json` and logging only
the exception type. Nothing should reach it; it exists so that if something
does, a client gets a well-formed document rather than a stack trace.
