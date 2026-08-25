import type { DateValue } from "./types";

/**
 * Age in whole years, derived client-side for display only.
 *
 * Returns `null` unless the source recorded a **day-precision** birth date.
 * A year-only or month-only value cannot yield an age without inventing the
 * missing components — "1958" spans a whole year, so any age computed from it
 * would be wrong for part of that range. The rest of this application refuses
 * to expand partial dates, and this is the same rule applied to a derived
 * value: absent precision means no age, not a guessed one.
 *
 * Not part of the API contract and never persisted. `today` is injectable so
 * the calculation is deterministic under test.
 */
export function deriveAge(birthDate: DateValue | null, today: Date = new Date()): number | null {
  if (!birthDate || birthDate.precision !== "day") return null;

  const [yearPart, monthPart, dayPart] = birthDate.value.split("-");
  if (yearPart === undefined || monthPart === undefined || dayPart === undefined) return null;

  const year = Number(yearPart);
  const month = Number(monthPart);
  const day = Number(dayPart);
  if (!Number.isInteger(year) || !Number.isInteger(month) || !Number.isInteger(day)) return null;

  // UTC throughout: the birth date carries no timezone, so using local time
  // would make the answer depend on where the page is rendered.
  let age = today.getUTCFullYear() - year;
  const monthNow = today.getUTCMonth() + 1;
  const hasHadBirthdayThisYear =
    monthNow > month || (monthNow === month && today.getUTCDate() >= day);
  if (!hasHadBirthdayThisYear) age -= 1;

  return age >= 0 && age < 150 ? age : null;
}
