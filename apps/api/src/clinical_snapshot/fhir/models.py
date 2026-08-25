"""A lenient Pydantic model of the FHIR R4 subset this application consumes.

Two deliberate departures from a strict FHIR validator:

1. **Every field is optional.** Production interoperability feeds omit
   required elements constantly. A missing `Condition.category` should
   degrade that one condition's classification, not reject the bundle.

2. **Unknown fields are preserved** (`extra="allow"`). We model what we
   render; we do not discard what we do not understand. Silently dropping an
   element we failed to anticipate is how data-loss bugs start.

Validation failures are reported as issues by the loader, never raised.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class FhirBase(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


# --------------------------------------------------------------------------
# Datatypes
# --------------------------------------------------------------------------


class Coding(FhirBase):
    system: str | None = None
    code: str | None = None
    display: str | None = None
    version: str | None = None

    @property
    def has_display(self) -> bool:
        return bool(self.display and self.display.strip())


class CodeableConcept(FhirBase):
    coding: list[Coding] = Field(default_factory=list)
    text: str | None = None

    @property
    def primary(self) -> Coding | None:
        """The first coding, which is what we render.

        FHIR permits several codings as translations of one concept. We do not
        attempt to pick a "best" system -- that is a terminology decision we
        have no basis to make here.
        """
        return self.coding[0] if self.coding else None

    @property
    def primary_code(self) -> str | None:
        return self.primary.code if self.primary else None


class Reference(FhirBase):
    reference: str | None = None
    type: str | None = None
    display: str | None = None
    identifier: Identifier | None = None


class Identifier(FhirBase):
    use: str | None = None
    system: str | None = None
    value: str | None = None
    type: CodeableConcept | None = None


class HumanName(FhirBase):
    use: str | None = None
    text: str | None = None
    family: str | None = None
    given: list[str] = Field(default_factory=list)
    prefix: list[str] = Field(default_factory=list)
    suffix: list[str] = Field(default_factory=list)


class ContactPoint(FhirBase):
    system: str | None = None
    value: str | None = None
    use: str | None = None


class Address(FhirBase):
    use: str | None = None
    line: list[str] = Field(default_factory=list)
    city: str | None = None
    state: str | None = None
    postalCode: str | None = None
    country: str | None = None


class Quantity(FhirBase):
    value: float | None = None
    unit: str | None = None
    system: str | None = None
    code: str | None = None


class Period(FhirBase):
    start: str | None = None
    end: str | None = None


class Extension(FhirBase):
    url: str | None = None
    valueString: str | None = None
    valueCode: str | None = None
    valueCoding: Coding | None = None
    extension: list[Extension] = Field(default_factory=list)

    def sub(self, url: str) -> Extension | None:
        return next((e for e in self.extension if e.url == url), None)


class Meta(FhirBase):
    profile: list[str] = Field(default_factory=list)
    versionId: str | None = None
    lastUpdated: str | None = None


# --------------------------------------------------------------------------
# Resources
# --------------------------------------------------------------------------


class DomainResource(FhirBase):
    resourceType: str
    id: str | None = None
    meta: Meta | None = None
    extension: list[Extension] = Field(default_factory=list)

    @property
    def key(self) -> str:
        """`ResourceType/id`, the form used by relative references."""
        return f"{self.resourceType}/{self.id}"


class PatientLink(FhirBase):
    """The element a source system uses to assert two Patients are related.

    Its absence is the strongest evidence we have against merging records --
    FHIR gives sources a first-class way to say "these are the same person",
    and this bundle does not use it.
    """

    other: Reference | None = None
    type: str | None = None  # replaced-by | replaces | refer | seealso


class Patient(DomainResource):
    resourceType: str = "Patient"
    identifier: list[Identifier] = Field(default_factory=list)
    active: bool | None = None
    name: list[HumanName] = Field(default_factory=list)
    telecom: list[ContactPoint] = Field(default_factory=list)
    gender: str | None = None
    birthDate: str | None = None
    address: list[Address] = Field(default_factory=list)
    link: list[PatientLink] = Field(default_factory=list)


class Encounter(DomainResource):
    resourceType: str = "Encounter"
    status: str | None = None
    class_: Coding | None = Field(default=None, alias="class")
    type: list[CodeableConcept] = Field(default_factory=list)
    subject: Reference | None = None
    period: Period | None = None


class Condition(DomainResource):
    resourceType: str = "Condition"
    clinicalStatus: CodeableConcept | None = None
    verificationStatus: CodeableConcept | None = None
    category: list[CodeableConcept] = Field(default_factory=list)
    code: CodeableConcept | None = None
    subject: Reference | None = None
    encounter: Reference | None = None
    onsetDateTime: str | None = None
    recordedDate: str | None = None


class ObservationComponent(FhirBase):
    code: CodeableConcept | None = None
    valueQuantity: Quantity | None = None
    valueString: str | None = None


class Observation(DomainResource):
    resourceType: str = "Observation"
    status: str | None = None
    category: list[CodeableConcept] = Field(default_factory=list)
    code: CodeableConcept | None = None
    subject: Reference | None = None
    encounter: Reference | None = None
    performer: list[Reference] = Field(default_factory=list)
    effectiveDateTime: str | None = None
    valueQuantity: Quantity | None = None
    valueString: str | None = None
    component: list[ObservationComponent] = Field(default_factory=list)
    referenceRange: list[dict[str, object]] = Field(default_factory=list)
    interpretation: list[CodeableConcept] = Field(default_factory=list)


class Dosage(FhirBase):
    text: str | None = None


class MedicationRequest(DomainResource):
    resourceType: str = "MedicationRequest"
    status: str | None = None
    intent: str | None = None
    medicationCodeableConcept: CodeableConcept | None = None
    medicationReference: Reference | None = None
    subject: Reference | None = None
    encounter: Reference | None = None
    authoredOn: str | None = None
    dosageInstruction: list[Dosage] = Field(default_factory=list)


class AllergyReaction(FhirBase):
    manifestation: list[CodeableConcept] = Field(default_factory=list)
    severity: str | None = None
    description: str | None = None


class AllergyIntolerance(DomainResource):
    resourceType: str = "AllergyIntolerance"
    clinicalStatus: CodeableConcept | None = None
    verificationStatus: CodeableConcept | None = None
    type: str | None = None
    category: list[str] = Field(default_factory=list)
    criticality: str | None = None
    code: CodeableConcept | None = None
    patient: Reference | None = None
    recordedDate: str | None = None
    reaction: list[AllergyReaction] = Field(default_factory=list)


class UnknownResource(DomainResource):
    """Any resourceType we do not model. Retained so it can be counted and
    reported rather than vanishing from the entry tally."""


# --------------------------------------------------------------------------
# Bundle
# --------------------------------------------------------------------------


class BundleEntry(FhirBase):
    fullUrl: str | None = None
    # Kept raw so the loader controls per-resource parse-error reporting.
    resource: dict[str, object] | None = None


class Bundle(FhirBase):
    resourceType: str = "Bundle"
    id: str | None = None
    type: str | None = None
    timestamp: str | None = None
    total: int | None = None
    entry: list[BundleEntry] = Field(default_factory=list)


RESOURCE_MODELS: dict[str, type[DomainResource]] = {
    "Patient": Patient,
    "Encounter": Encounter,
    "Condition": Condition,
    "Observation": Observation,
    "MedicationRequest": MedicationRequest,
    "AllergyIntolerance": AllergyIntolerance,
}

Reference.model_rebuild()
Extension.model_rebuild()
