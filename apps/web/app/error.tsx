"use client";

/**
 * Last-resort boundary for anything `page.tsx` does not handle itself.
 *
 * A failure to reach the API is handled inline, with specific guidance. This
 * catches the rest. It deliberately does not render `error.message`: on a
 * clinical page an unexpected error could carry fragments of a payload, and a
 * digest is enough to correlate with a server log.
 */
export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <main className="page">
      <div className="fatal" role="alert">
        <h1>Something went wrong loading this snapshot</h1>
        <p>
          No clinical data is shown, because the application could not confirm what it
          would be showing. Nothing has been partially rendered.
        </p>
        {error.digest ? (
          <p className="small">
            Reference for the server log: <code>{error.digest}</code>
          </p>
        ) : null}
        <button type="button" className="retry" onClick={reset}>
          Try again
        </button>
      </div>
    </main>
  );
}
