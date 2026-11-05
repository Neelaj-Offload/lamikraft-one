import { Badge } from "@/components/ui/badge";
import { InfoIcon } from "@/components/ui/icons";
import { LinkButton } from "@/components/ui/link";
import { PageHeader } from "@/components/ui/page-header";
import { StateView } from "@/components/ui/states";
import { sectionLabelClasses } from "@/components/ui/styles";
import type { RouteId } from "@/lib/routes";
import { areaMessages, type AreaCopy } from "@/messages/areas";
import { DeliveredPart } from "./area-part";

export type PlannedArea = "operations";

/**
 * An honest overview for an area no slice has delivered yet: what it will hold and when, with no
 * figures, cards or progress of any kind, and the two places that do have work today.
 */
export function AreaOverview({ area }: { area: PlannedArea }) {
  const copy: AreaCopy = areaMessages[area];
  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <PageHeader title={copy.title} intro={copy.intro} />
      <StateView
        icon={<InfoIcon />}
        title={copy.stateTitle}
        actions={
          <>
            <LinkButton href="/today" variant="primary">
              {areaMessages.today}
            </LinkButton>
            <LinkButton href="/inbox">{areaMessages.inbox}</LinkButton>
          </>
        }
      >
        <p>{copy.stateBody}</p>
        <p className="mt-1">{copy.liveNote ?? areaMessages.nothingOn}</p>
      </StateView>
      <section aria-labelledby={`${area}-parts`} className="flex flex-col gap-2">
        <h2 id={`${area}-parts`} className={sectionLabelClasses}>
          {copy.partsHeading}
        </h2>
        <ul className="flex flex-col divide-y rounded-lg border bg-surface px-4">
          {copy.parts.map((part) => (
            <li key={part.label} className="flex min-h-12 flex-wrap items-center justify-between gap-x-4 gap-y-1 py-2">
              {part.routeId ? (
                <DeliveredPart label={part.label} routeId={part.routeId as RouteId} />
              ) : (
                <>
                  <span className="text-ink">{part.label}</span>
                  <Badge>{areaMessages.planned(part.slice)}</Badge>
                </>
              )}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
