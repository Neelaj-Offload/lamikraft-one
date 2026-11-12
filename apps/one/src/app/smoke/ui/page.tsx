import { CoreGallery } from "~/ui/_gallery-core";
import { DataGallery } from "~/ui/_gallery-data";
import { ThemeToggle } from "~/ui/theme-toggle";

/** Review page for the component set. Temporary: removed with /smoke before release. */
export default function UiReviewPage() {
  return (
    <>
      <div className="app-scene" aria-hidden />
      <main className="relative z-[1] mx-auto flex max-w-[1200px] flex-col gap-10 p-5 md:p-10">
        <header className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="t-overline text-gold-strong">Component review</p>
            <h1 className="t-display-md">
              The Lamikraft <em>kit</em>
            </h1>
          </div>
          <ThemeToggle />
        </header>
        <CoreGallery />
        <DataGallery />
      </main>
    </>
  );
}
