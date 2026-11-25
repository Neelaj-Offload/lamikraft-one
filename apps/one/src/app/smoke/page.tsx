import { routes } from "~/lib/routes";
import { Icon } from "~/ui/icon";
import { SmokeClient } from "./smoke-client";

/** Temporary: proves tokens, fonts, the lk-* classes and the shared data layer load. Removed before release. */
export default function SmokePage() {
  return (
    <main className="lk-scene lk-scene-blobs min-h-dvh">
      <section className="lk-glass lk-glass-pad-lg mx-auto mt-16 max-w-xl">
        <p className="t-overline text-gold-strong">Smoke test</p>
        <h1 className="t-display-md">
          Built to <em>perform</em>
        </h1>
        <p className="t-body-lg text-ink-2">
          {routes.length} routes in the shared manifest. <Icon name="sparkles" className="inline" />
        </p>
        <SmokeClient />
      </section>
    </main>
  );
}
