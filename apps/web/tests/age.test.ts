import { describe, expect, it } from "vitest";

import { deriveAge } from "@/lib/age";
import type { DateValue } from "@/lib/types";

const date = (value: string, precision: DateValue["precision"]): DateValue => ({ value, precision });

describe("deriveAge — precision gating", () => {
  it("derives an age from a day-precision birth date", () => {
    expect(deriveAge(date("1958-03-12", "day"), new Date("2026-08-25T00:00:00Z"))).toBe(68);
  });

  it("omits the age for a year-only birth date", () => {
    expect(deriveAge(date("1958", "year"), new Date("2026-08-25T00:00:00Z"))).toBeNull();
  });

  it("omits the age for a month-only birth date", () => {
    expect(deriveAge(date("1958-03", "month"), new Date("2026-08-25T00:00:00Z"))).toBeNull();
  });

  it("omits the age when there is no birth date at all", () => {
    expect(deriveAge(null, new Date("2026-08-25T00:00:00Z"))).toBeNull();
  });

  it("omits the age for an instant-precision value", () => {
    // A FHIR `date` never carries a time; anything that does is anomalous, so
    // the conservative answer is no age rather than a guess.
    expect(deriveAge(date("1958-03-12T00:00:00Z", "instant"), new Date("2026-08-25T00:00:00Z")))
      .toBeNull();
  });
});

describe("deriveAge — birthday boundary", () => {
  const dob = date("1958-03-12", "day");

  it("the day before the birthday is still the previous age", () => {
    expect(deriveAge(dob, new Date("2026-03-11T23:59:59Z"))).toBe(67);
  });

  it("on the birthday the age increments", () => {
    expect(deriveAge(dob, new Date("2026-03-12T00:00:00Z"))).toBe(68);
  });

  it("the day after the birthday holds", () => {
    expect(deriveAge(dob, new Date("2026-03-13T00:00:00Z"))).toBe(68);
  });

  it("the last day of the preceding month is the previous age", () => {
    expect(deriveAge(dob, new Date("2026-02-28T00:00:00Z"))).toBe(67);
  });

  it("the first day of the following month is the new age", () => {
    expect(deriveAge(dob, new Date("2026-04-01T00:00:00Z"))).toBe(68);
  });

  it("29 February birth dates do not crash in a non-leap year", () => {
    const leapling = date("2000-02-29", "day");
    expect(deriveAge(leapling, new Date("2026-02-28T00:00:00Z"))).toBe(25);
    expect(deriveAge(leapling, new Date("2026-03-01T00:00:00Z"))).toBe(26);
  });

  it("is computed in UTC so it does not depend on where the page renders", () => {
    // 2026-03-11T23:00Z is already 2026-03-12 in UTC+2, but UTC governs.
    expect(deriveAge(dob, new Date("2026-03-11T23:00:00Z"))).toBe(67);
  });
});

describe("deriveAge — implausible input", () => {
  it("returns null for a future birth date rather than a negative age", () => {
    expect(deriveAge(date("2030-01-01", "day"), new Date("2026-08-25T00:00:00Z"))).toBeNull();
  });

  it("returns null for an implausibly distant birth date", () => {
    expect(deriveAge(date("1800-01-01", "day"), new Date("2026-08-25T00:00:00Z"))).toBeNull();
  });

  it("returns null for a malformed day-precision value", () => {
    expect(deriveAge(date("not-a-date", "day"), new Date("2026-08-25T00:00:00Z"))).toBeNull();
  });
});
