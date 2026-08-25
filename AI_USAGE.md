# AI Usage

## Tool and model

**Claude Code** (CLI), model **`claude-opus-5`**, used for the whole build in a
single working session. No other AI provider was used. The application itself
makes **no** LLM calls at runtime — the `ANTHROPIC_API_KEY` in `.env` funds the
coding assistant, not a product feature. That was a deliberate decision, taken
early: the brief never asks for an LLM in the application, and adding one
uninvited to a *clinical safety* exercise reads as poor judgement rather than
initiative. An unrequested AI feature would also have been the least trustworthy
component in a codebase whose entire premise is not guessing.

## How the work was broken up

Prompts were deliberately staged rather than asking for "build the app":

1. **Investigation before code.** The first prompt forbade writing any
   application code and asked for a repository assessment, a data inventory, an
   enumeration of the bundle's defects, and a proposed architecture. This turned
   out to be the highest-leverage decision of the project — the eleven
   data-quality problems in the README were found by auditing the bundle, and
   six of them are not mentioned in the brief.
2. **Domain modelling** — indexing, reference resolution, dates, terminology.
3. **Normalization** — patient reconciliation, clinical safety policy, snapshot.
4. **API**, then **frontend**, each with its own review pass.
5. **Adversarial review** — separate prompts for backend review, accessibility,
   security, and a lead-engineer pass, each explicitly instructed to *list
   findings and stop*, not to fix.

Splitting "find problems" from "fix problems" mattered. When the same pass does
both, the fixes justify the findings.

## Where it accelerated the work

- **Parametrised test tables.** The 53-case status cross-product in
  `test_safety.py` and the eight reconciliation scenarios are mechanical to
  generate and fast to review. This is the clearest win.
- **Boilerplate.** Pydantic response DTOs mirroring the domain dataclasses,
  TypeScript type mirrors of the API contract, Dockerfiles, compose, Makefile.
- **Domain research**, all verified against the specification before being
  encoded: US Core must-support elements, FHIR invariant `bdl-1` (`Bundle.total`
  is only valid on `searchset`/`history`), the `urn:uuid:` validity rule, and the
  relative-reference resolution rule that makes this bundle's references
  strictly unresolvable.
- **Mechanical refactors** — promoting private members to a public API surface,
  splitting long functions, rewrapping to the line limit.

## Human review

Every generated file was read before acceptance. Three mechanisms did most of
the catching, and two of them caught things reading did not:

- **`mypy --strict`** over `domain/` and `fhir/`.
- **The safety invariant suite** (`apps/api/tests/safety/`), which asserts
  properties against the serialized HTTP payload rather than domain objects.
- **Running the app** and asserting against rendered output, not just unit tests.

## Corrections I made to AI output

These all happened during this build. Each is recorded because the reasoning is
the point, not the diff.

### 1. Partial-date coercion — rejected

The natural way to stop `datetime.fromisoformat("2019")` raising is to pad the
value to `2019-01-01`. That fabricates a January 1st onset for a diabetes-coded
condition, and would have silently affected five other values in the bundle.

Rejected in favour of a `PartialDate` value object that carries its own
precision and deliberately exposes **no** method returning a padded date.
Ordering uses interval bounds that never reach the payload. When prompt 6 later
asked for a "parsed value where safe", the same reasoning applied: `parsed_date`
and `parsed_instant` are `None` for year and month precision, because every
candidate value would be invented.

Enforced by `test_every_rendered_date_appears_verbatim_in_the_source`.

### 2. Terminology invention — rejected

Four codes in the bundle have no display: `E11.9`, `4548-4`, `849574`,
`91936005`. A model can produce all four labels instantly and confidently.

Rejected for two reasons. The first is that it is unsourced. The second is
specific to this bundle and took reading the data to see:
`allergyintolerance-003` carries SNOMED `91936005` with no display, while
`allergyintolerance-001` carries the display "Penicillin" on a code that is
**not a well-formed SNOMED identifier**. Resolving `91936005` from model
knowledge could present two entries that are one concept, or equate a *confirmed
high-criticality* allergy with an *unconfirmed unable-to-assess* one.

The map was narrowed to CodeSystems defined by the FHIR specification itself,
each entry citing its source. The scope rule is written into
`terminology/displays.yaml` so the next person cannot widen it by accident. It
also drove the decision to perform **no de-duplication of allergies at all** —
de-duplication means trusting codes, and one of these two does not validate.

### 3. Patient merging — rejected, then partially reversed

The two Patient records share surname, first name, sex, normalised address and
birth year. The obvious implementation merges them, which pulls an *active*
medication whose RxNorm code has no display — so the drug cannot even be named —
into the other patient's list.

I rejected the merge. The source argues against it: the two MRNs are different
values **in the same assigning system**, neither record carries `Patient.link`,
and the birth dates agree only because one is year-precision.

**Then I reversed part of my own position.** My first design hid the duplicate's
medication behind a warning banner. Re-reading the brief — *"say so rather than
hiding it"* — showed that was wrong under asymmetric loss: if the records *are*
the same person, omitting an active medication breaks medication reconciliation,
which is its own safety failure. The final design shows it, attributed to the
record it came from, with same-person status explicitly marked unconfirmed. The
merge is still refused. This reversal is documented because being wrong in the
safe direction is still being wrong.

### 4. Status-filtering precedence — a bug avoided by reading the spec

`Condition` and `AllergyIntolerance` have no `status` element, so the retracted
ones are reachable only via `verificationStatus`. Both *also* carry a non-active
`clinicalStatus`. A `clinicalStatus`-first rule hides them **coincidentally**,
reports the wrong reason to the user, and still leaves the retracted creatinine
(14.7 mg/dL — roughly ten times normal, in a patient on an ACE inhibitor) and a
phantom encounter on screen. Rule order is now explicit and covered by a
53-case table.

### 5. Code-shape validation — added, not suggested

Nothing in the brief mentions it. It surfaced from asking whether a code
*validates against the system it claims*, rather than trusting the pair.
`allergyintolerance-001` declares SNOMED CT but carries `7980-2` — hyphenated,
LOINC-shaped. The display is kept (discarding a high-criticality allergy's label
is its own harm) but marked unvalidated and barred from coded logic.

### 6. A retracted-data leak caught by the test suite, not by review

Adding `member_resource_ids` to the reconciliation result (prompt 8) listed
*every* resource each patient owned — including the four retracted ones — and
that field sits inside the snapshot's `data` envelope. Retracted resource ids
leaked back into the clinician-facing payload.

I did not catch this by reading the diff. `test_no_retracted_id_appears_in_any_clinical_section`
failed. The fix filters to displayable resources only. This is the strongest
argument in the repo for writing invariant tests before adding features.

### 7. A determinism bug in code I had just written

`BundleIndex.for_patient_reference` used `zip(seen, matched)` where `seen` was a
**set** — pairing arbitrary set-iteration order against an ordered list. It
would have produced non-deterministic resource ordering. Found while writing the
tests, before it ever ran in anger.

### 8. Over-broad test assertions — corrected twice

Two assertions I wrote were wrong in a way that would have made them useless:

- "no retracted id appears in the payload" scanned the whole response
  **including `issues`**, where those ids must appear, because reporting the
  retraction is a requirement. Narrowed to `data`, and paired with a positive
  test asserting the issue log *does* report all four.
- "no observation row renders an abnormal indicator" matched the section note
  that *explains nothing is flagged*. Scoped to the value row.

### 9. Silent lenience in a parser — rejected

The reference parser filtered out empty path segments, so `Patient//patient-001`
resolved successfully. A double slash is a malformed reference; collapsing it is
exactly the kind of helpfulness this resolver must not have.

### 10. An API design flaw caught by the type checker

The assembler's dispatch reused a single `view` variable across five resource
branches. It ran correctly, but `mypy --strict` flagged
`view.category_declared == "vital-signs"` as a non-overlapping comparison — the
inferred type was `ConditionView`, whose `category_declared` is a `bool`. Split
into per-branch names.

## What I did not delegate

The architecture, the clinical-safety rules and their precedence, the decision
not to merge the Patient records, the decision to withhold the retracted
creatinine value, the scope rule for the terminology map, the decision to
withhold the SSN entirely rather than mask it, and the acceptance of every
change were mine. The review passes (backend, accessibility, security, lead)
were run as adversarial prompts that produced *lists*, and I chose what to act
on. Where I disagreed with a suggestion, I said so and left it — the reviews in
this repository include findings I have deliberately not fixed, with reasons.

The AI wrote a large share of the lines. It did not decide what the application
is allowed to claim about a patient.
