import { Page } from "./page";

/**
 * Build-time scaffold only: marks a route whose screen has not been built yet, so typed routes
 * and navigation compile while screens are built in parallel. `node scripts/stubs.mjs --check`
 * fails while any route still renders this; none may remain at release.
 */
export function RouteStub({ path }: { path: string }) {
  return (
    <Page width="narrow">
      <div className="lk-glass lk-glass-pad-lg">
        <p className="t-overline text-ink-3">Being built</p>
        <h1 className="t-h2">{path}</h1>
      </div>
    </Page>
  );
}
