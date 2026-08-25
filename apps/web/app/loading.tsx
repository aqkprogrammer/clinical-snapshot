/**
 * Shown while the snapshot is being fetched and normalized.
 *
 * The skeleton mirrors the real layout -- patient header, two banners, a
 * two-column card grid -- so the page does not reflow when content arrives.
 * `role="status"` with `aria-busy` means a screen reader is told the page is
 * loading rather than being read an empty document.
 */
export default function Loading() {
  return (
    <main className="page" role="status" aria-busy="true" aria-live="polite">
      <span className="sr-only">Loading clinical snapshot…</span>

      <div className="patient-header">
        <div className="skeleton skeleton-title" />
        <div className="skeleton skeleton-line" style={{ width: "28%" }} />
        <div className="patient-facts" style={{ marginTop: 18 }}>
          {Array.from({ length: 6 }).map((_, index) => (
            <div key={index} style={{ minWidth: 108 }}>
              <div className="skeleton skeleton-line" style={{ width: "62%", height: 9 }} />
              <div className="skeleton skeleton-line" style={{ width: "88%" }} />
            </div>
          ))}
        </div>
      </div>

      {[0, 1].map((index) => (
        <div key={index} className="banner banner-medium" style={{ borderColor: "var(--line)", background: "var(--surface)" }}>
          <div style={{ flex: 1 }}>
            <div className="skeleton skeleton-line" style={{ width: "30%" }} />
            <div className="skeleton skeleton-line" style={{ width: "82%", marginBottom: 0 }} />
          </div>
        </div>
      ))}

      <div className="grid">
        {[0, 1].map((column) => (
          <div key={column}>
            {[0, 1, 2].map((card) => (
              <section key={card} className="card" aria-hidden>
                <div className="skeleton skeleton-line" style={{ width: "34%", height: 10 }} />
                <div style={{ marginTop: 14 }}>
                  <div className="skeleton skeleton-line" style={{ width: "72%", height: 15 }} />
                  <div className="skeleton skeleton-line" style={{ width: "54%" }} />
                  <div className="skeleton skeleton-line" style={{ width: "63%", marginBottom: 0 }} />
                </div>
              </section>
            ))}
          </div>
        ))}
      </div>
    </main>
  );
}
