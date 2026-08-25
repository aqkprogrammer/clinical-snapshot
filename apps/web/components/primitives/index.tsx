/**
 * The uncertainty primitives.
 *
 * Every place the snapshot could quietly imply more confidence than the data
 * supports goes through one of these. They exist so that rendering something
 * honestly is the path of least resistance and rendering it dishonestly takes
 * deliberate effort.
 */

import type { Coding, DateValue, ReferenceValue } from "@/lib/types";

/* -- dates --------------------------------------------------------------- */

const MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

/**
 * Renders a date at exactly the precision the source recorded.
 *
 * A year-only value shows as "2019 (year only)". It is never widened to a day,
 * and the parenthetical is not decoration -- it is the difference between
 * "diagnosed in 2019" and "diagnosed on 1 January 2019".
 */
export function PartialDate({ date, fallback = "not recorded" }: {
  date: DateValue | null;
  fallback?: string;
}) {
  if (!date) return <span className="unknown-value">{fallback}</span>;

  switch (date.precision) {
    case "year":
      return (
        <span>
          {date.value} <span className="precision-hint">(year only)</span>
        </span>
      );
    case "month": {
      const [year, month] = date.value.split("-");
      const label = month ? `${MONTHS[Number(month) - 1] ?? month} ${year}` : date.value;
      return (
        <span>
          {label} <span className="precision-hint">(month only)</span>
        </span>
      );
    }
    case "day": {
      const [year, month, day] = date.value.split("-");
      if (!year || !month || !day) return <span>{date.value}</span>;
      return <span>{`${day} ${MONTHS[Number(month) - 1] ?? month} ${year}`}</span>;
    }
    default: {
      const date_ = new Date(date.value);
      if (Number.isNaN(date_.getTime())) return <span>{date.value}</span>;
      const day = String(date_.getUTCDate()).padStart(2, "0");
      const month = MONTHS[date_.getUTCMonth()];
      const time = date_.toISOString().slice(11, 16);
      return <span>{`${day} ${month} ${date_.getUTCFullYear()}, ${time} UTC`}</span>;
    }
  }
}

/* -- codings ------------------------------------------------------------- */

/**
 * Renders a coded concept.
 *
 * When the source supplied no display and we have no auditable lookup, this
 * shows "ICD-10-CM E11.9 — display unavailable" in the unknown treatment. It
 * does not fall back to the raw code styled as though it were a name, and it
 * never guesses.
 */
export function CodeLabel({ coding, className }: { coding: Coding; className?: string }) {
  const systemLabel = coding.systemName ?? coding.system ?? "code";

  if (coding.displayStatus === "unresolved") {
    return (
      <span className={className}>
        <span className="unknown-value">
          {systemLabel} {coding.code} — display unavailable
        </span>{" "}
        <Badge tone="unknown" title="No human-readable name is available for this code, and none was inferred.">
          no display
        </Badge>
      </span>
    );
  }

  return (
    <span className={className}>
      <span>{coding.display}</span>{" "}
      {coding.code ? (
        <span className="code-chip" title={coding.system ?? undefined}>
          {systemLabel} {coding.code}
        </span>
      ) : null}
      {coding.displayStatus === "from-source-unvalidated" ? (
        <>
          {" "}
          <Badge tone="danger">code / system mismatch</Badge>
        </>
      ) : null}
      {coding.displayStatus === "resolved-local" && coding.displaySourceDetail ? (
        <>
          {" "}
          <Badge tone="neutral" title={`Display resolved from ${coding.displaySourceDetail}`}>
            spec display
          </Badge>
        </>
      ) : null}
    </span>
  );
}

/**
 * The reason a code failed validation, rendered visibly.
 *
 * This used to live only in the badge's `title`. A tooltip is unreachable by
 * keyboard, absent on touch, and inconsistently announced by screen readers --
 * which is not acceptable for the explanation of why a clinical label cannot
 * be trusted. The badge stays as the scannable marker; this is the substance.
 */
export function CodeCaveat({ coding }: { coding: Coding }) {
  if (!coding.codeSystemMismatch || !coding.mismatchReason) return null;
  return (
    <p className="code-caveat">
      <strong>Unvalidated label.</strong> {coding.mismatchReason}. The name shown was
      supplied by the source and has not been checked against {coding.systemName ?? "its code system"};
      the code is excluded from any coded matching.
    </p>
  );
}

/* -- references ---------------------------------------------------------- */

/**
 * "No encounter recorded" and "the encounter is missing from the bundle" are
 * different clinical statements. This keeps them visually distinct.
 */
export function ReferenceLabel({ reference, absent = "not recorded" }: {
  reference: ReferenceValue | null;
  absent?: string;
}) {
  if (!reference) return <span className="muted">{absent}</span>;
  if (reference.resolved) {
    return <span>{reference.display ?? reference.reference}</span>;
  }
  return (
    <span>
      <span className="unknown-value">unresolved</span>{" "}
      <span className="mono muted">({reference.reference} not present in bundle)</span>
    </span>
  );
}

/* -- badges -------------------------------------------------------------- */

export type Tone = "neutral" | "warn" | "danger" | "unknown" | "ok";

export function Badge({ tone = "neutral", title, children }: {
  tone?: Tone;
  title?: string;
  children: React.ReactNode;
}) {
  return (
    <span className={`badge badge-${tone}`} title={title}>
      {children}
    </span>
  );
}

/** Caveats emitted by the classifier that must ride along with an item. */
export function FlagBadges({ flags }: { flags: string[] }) {
  const tones: Record<string, { tone: Tone; label: string; title: string }> = {
    unconfirmed: {
      tone: "warn",
      label: "unconfirmed",
      title: "The source has not confirmed this record. It is shown because suppressing it could be more harmful than showing it.",
    },
    cancelled: { tone: "warn", label: "cancelled", title: "This did not take place." },
    "on-hold": { tone: "warn", label: "on hold", title: "The order is active but currently on hold." },
    "status-absent": { tone: "unknown", label: "status absent", title: "The source recorded no status." },
  };
  return (
    <>
      {flags.map((flag) => {
        const spec = tones[flag] ?? { tone: "neutral" as Tone, label: flag, title: flag };
        return (
          <Badge key={flag} tone={spec.tone} title={spec.title}>
            {spec.label}
          </Badge>
        );
      })}
    </>
  );
}

/* -- misc ---------------------------------------------------------------- */

export function Empty({ children }: { children: React.ReactNode }) {
  return <p className="empty">{children}</p>;
}

export function SectionNote({ children }: { children: React.ReactNode }) {
  return <p className="section-note">{children}</p>;
}
