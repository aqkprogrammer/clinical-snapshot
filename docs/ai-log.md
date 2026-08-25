# AI usage — running log

Scratch notes captured during the build, distilled into `AI_USAGE.md` at the end.
Tool: Claude Code (CLI), model `claude-opus-5`.

---

## Corrections and rejections

### 1. Partial-date coercion (rejected)
The natural way to make `datetime.fromisoformat("2019")` stop raising is to pad the
value to `2019-01-01`. That fabricates a January 1st onset for a diabetes-coded
condition that the source never recorded, and it would have silently affected five
other values. Rejected in favour of a `PartialDate` value object that carries its
own precision and deliberately exposes **no** method returning a padded date. Sorting
uses interval bounds that never reach the payload.
Guarded by `tests/safety` → `test_every_rendered_date_appears_verbatim_in_the_source`.

### 2. Terminology invention (rejected)
Four codes in the bundle have no display: `E11.9`, `4548-4`, `849574`, `91936005`.
An LLM can produce all four labels instantly and confidently. Doing so would be
wrong twice over — it is unsourced, and in the allergy case it risks presenting
`allergyintolerance-003` as a duplicate of `allergyintolerance-001`, whose display
says "Penicillin". Rejected in favour of a curated map limited to CodeSystems
defined by the FHIR spec itself, with everything else resolving to `null`.
The scope rule is written down in `terminology/displays.yaml`.

### 3. Demographic auto-merge (rejected, then partially reversed)
The two Patient records share surname, first name, sex, normalised address and
birth year. The obvious implementation merges them. That would pull an *active*
medication with no resolvable drug name into the other patient's list.

Initial position: hide the medication behind a warning banner.
**Reversed after re-reading the brief** ("say so rather than hiding it"). Under
asymmetric loss, hiding an active medication is itself a safety failure if the
records *are* the same person. Final design shows it, attributed to the record it
came from, with same-person status explicitly marked unconfirmed. The merge itself
is still refused — `mergePerformed` is False unless the source used `Patient.link`.

### 4. Code-system validation (added, not suggested)
`allergyintolerance-001` declares SNOMED CT but carries `7980-2` — hyphenated and
LOINC-shaped. Nothing in the brief mentions this; it surfaced from validating code
*shape* against the declared system rather than trusting the pair. The display is
kept (discarding a high-criticality allergy's label is its own harm) but marked
unvalidated and barred from coded logic.

### 5. `verificationStatus` before `clinicalStatus` (ordering bug avoided)
`Condition` and `AllergyIntolerance` have no `status` element, so the retracted
ones are only reachable via `verificationStatus`. Both also carry a non-active
`clinicalStatus`, so a clinicalStatus-first rule hides them *coincidentally* and
reports the wrong reason to the user. Rule order is now explicit and covered by a
53-case parametrised table.

### 6. Over-broad safety invariant (test bug, caught by the test failing)
The first version of "no retracted id appears in the payload" scanned the whole
response including `issues` — where those ids *must* appear, because reporting the
retraction is a requirement. Narrowed to the `data` envelope and paired with a
positive test asserting the issue log does report all four.

### 7. `IssueLog.add(**detail)` name collision (caught at runtime)
Detail keys were passed as `**kwargs`, so a detail named `code` collided with the
issue-code parameter. Replaced the `**kwargs` with an explicit `detail: dict`
rather than renaming the caller's key — the collision class is designed out.

### 8. Variable shadowing across branches (caught by `mypy --strict`)
The assembler's dispatch reused one `view` variable across resource types. It ran
correctly, but mypy flagged `view.category_declared == "vital-signs"` as a
non-overlapping comparison — the inferred type was `ConditionView`, whose
`category_declared` is a `bool`. Split into per-branch names.

---

## Where it accelerated

- Parametrised test tables (53 status combinations) — mechanical, fast to generate,
  fast to review.
- Pydantic response DTOs mirroring the domain dataclasses.
- Boilerplate: Dockerfiles, compose, TypeScript type mirrors.
- Domain research: US Core must-support elements, FHIR invariant `bdl-1`,
  `urn:uuid:` validity rules. All verified against the spec before being encoded.
