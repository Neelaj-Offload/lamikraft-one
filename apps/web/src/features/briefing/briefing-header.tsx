import type { ReactNode } from "react";
import { Badge } from "@/components/ui/badge";

export interface BriefingHeaderProps {
  /** Server-computed greeting in the user's zone, e.g. "Good morning, Meera." */
  greeting: string;
  /** The one factual sentence from the backend template; never composed here (absent in the fallback). */
  overview?: string | null;
  /** "Monday, 12 October · Updated 9:00 am" */
  meta: ReactNode;
  /** "Standard wording" when the AI phrasing is unavailable, "Demo" for the demo adapter. */
  wording?: { label: string; hint: string } | null;
}

/** A restrained large greeting and one factual sentence (build brief <design_direction>). */
export function BriefingHeader({ greeting, overview, meta, wording }: BriefingHeaderProps) {
  return (
    <header className="flex flex-col gap-2">
      <h1 className="text-[28px] leading-tight font-bold tracking-[-0.02em] text-ink md:text-[clamp(28px,3vw,40px)]">{greeting}</h1>
      {overview ? <p className="max-w-3xl text-lg text-ink md:text-xl">{overview}</p> : null}
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-ink-muted">
        {meta}
        {wording ? (
          <Badge tone="neutral">
            <span title={wording.hint}>{wording.label}</span>
            <span className="sr-only">: {wording.hint}</span>
          </Badge>
        ) : null}
      </p>
    </header>
  );
}
