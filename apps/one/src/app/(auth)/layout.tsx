import Image from "next/image";
import type { ReactNode } from "react";
import { BrandLogo } from "~/shell/brand";
import { LiveAnnouncer, ToastRegion } from "~/ui/toast";

/**
 * The signed-out frame: the form on the left with nothing competing for attention, and on wide
 * screens a single product photograph with one line of brand voice. Every signed-out screen
 * (sign in, two-step, reset, invitation, sign out) renders inside the left column.
 */
export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <>
      <div className="app-scene" aria-hidden />
      <div className="auth">
        <div className="auth-form">
          <header className="rise">
            <BrandLogo height={44} />
          </header>
          <main id="main" className="auth-form-body">
            {children}
          </main>
          <footer className="t-caption text-ink-3">Lamikraft One. Enquiries, quotations, stock and orders in one place.</footer>
        </div>
        <aside className="auth-stage scale-in" aria-label="Lamikraft">
          <Image
            src="/brand/professional-board.png"
            alt="A Lamikraft chopping board in use: sliced peppers and carrots on a walnut-toned board."
            fill
            sizes="(min-width: 1024px) 58vw, 0px"
            className="auth-stage-img"
            priority
          />
          <div className="auth-stage-shade" aria-hidden />
          <div className="auth-stage-copy">
            <p className="t-overline">Designed to perform</p>
            <p className="t-display-lg">
              Every board, every order, <em>accounted for</em>.
            </p>
            <p className="t-body-lg" style={{ opacity: 0.86 }}>
              One workspace for the whole journey: the first enquiry, the quotation, the stock on the shelf and the shipment out the door.
            </p>
          </div>
        </aside>
      </div>
      <ToastRegion />
      <LiveAnnouncer />
    </>
  );
}
