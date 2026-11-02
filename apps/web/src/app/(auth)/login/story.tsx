import { Link as RacLink } from "react-aria-components";
import { linkClasses } from "@/components/ui/styles";
import { authMessages as m } from "@/messages/auth";

/**
 * The short story below the fold: three beats in an editorial rhythm (numeral, title, one
 * paragraph). Plain text, no counts, no motion of its own; Lenis only smooths the scroll.
 */
export function LoginStory() {
  return (
    <section id="story" aria-labelledby="story-title" className="border-t bg-canvas">
      <div className="mx-auto flex max-w-6xl flex-col gap-16 px-6 py-20 md:px-12 md:py-28 lg:gap-24">
        <h2 id="story-title" className="text-xs font-semibold tracking-[0.12em] text-ink-muted uppercase">
          {m.showcase.scrollHint}
        </h2>
        <ol className="flex flex-col gap-16 lg:gap-24">
          {m.showcase.story.map((beat) => (
            <li key={beat.number} className="grid grid-cols-1 gap-4 border-t pt-8 md:grid-cols-[120px_minmax(0,1fr)] lg:grid-cols-[160px_minmax(0,1fr)_minmax(0,1fr)] lg:gap-10">
              <span aria-hidden="true" className="font-display text-5xl leading-none font-medium text-sand md:text-6xl">
                {beat.number}
              </span>
              <h3 className="font-display text-3xl leading-[1.05] font-medium tracking-[-0.02em] text-ink md:text-4xl lg:text-[44px]">{beat.title}</h3>
              <p className="max-w-prose text-lg leading-relaxed text-ink-muted md:text-xl">{beat.body}</p>
            </li>
          ))}
        </ol>
        <p>
          <RacLink href="#top" className={linkClasses}>
            {m.showcase.backToTop}
          </RacLink>
        </p>
      </div>
    </section>
  );
}
