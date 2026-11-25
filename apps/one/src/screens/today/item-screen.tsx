"use client";

import { useQueryClient } from "@tanstack/react-query";
import type { Route } from "next";
import { useRouter } from "next/navigation";
import { queryKeys } from "@/lib/api/query-keys";
import { useOnline } from "@/lib/hooks";
import { useNow, useSession } from "@/lib/session/context";
import { dueText, isNotFound, itemTone, kindLabel, SECTION_LABEL, uncertaintyText, useBriefingItem, useItemCommands } from "~/data/today";
import { riseAt } from "./rise";
import { Page, PageHeader, RecordHeader, Split } from "~/shell/page";
import { ErrorBlock } from "~/shell/states";
import { Badge, ButtonLink, DateText, EmptyState, FactStrip, GlassPanel, Icon, SkeletonText, TextLink, type Fact } from "~/ui";
import { allHref } from "./all-state";
import { ItemDialogs } from "./item-dialogs";
import { ItemActions } from "./item-row";

const CRUMBS = [{ label: "Today", href: "/today" as Route }, { label: "All of today", href: "/today/all" as Route }];

/** "sales.quote" becomes "quote": the last word of a record type, never the raw key. */
function typeWord(type: string): string {
  const word = (type.split(".").pop() ?? type).replaceAll("_", " ");
  return word === "quote" ? "Quotation" : word === "party" ? "Customer" : word.charAt(0).toUpperCase() + word.slice(1);
}

/**
 * One briefing item as a record: what it is, the suggested next step, why the briefing raised it,
 * the records it rests on, and its actions. The server answers only for an item of the current
 * briefing that the person can still see; anything else has left the briefing.
 */
export function ItemScreen({ issueId }: { issueId: string }) {
  const { bootstrap, zone } = useSession();
  const now = useNow() ?? new Date(bootstrap.server_now);
  const online = useOnline();
  const router = useRouter();
  const queryClient = useQueryClient();
  const query = useBriefingItem(issueId);

  const commands = useItemCommands({
    version: query.data?.version ?? null,
    offline: !online,
    onChanged: async (alsoInvalidate, outcome) => {
      await Promise.all(
        [...alsoInvalidate, queryKeys.briefings.item(issueId)].map((queryKey) => queryClient.invalidateQueries({ queryKey })),
      );
      // A finished command usually takes the item out of the briefing: go back to the day.
      if (outcome === "done") router.push("/today");
    },
  });

  if (query.isPending) {
    return (
      <Page>
        <PageHeader breadcrumb={CRUMBS} title="Briefing item" lead="Opening the item." />
        <GlassPanel padding="lg" role="status" aria-label="Loading the item" className="flex flex-col gap-8">
          <SkeletonText lines={3} />
          <SkeletonText lines={4} />
        </GlassPanel>
      </Page>
    );
  }

  if (query.isError) {
    return (
      <Page>
        <PageHeader breadcrumb={CRUMBS} title="Briefing item" />
        {isNotFound(query.error) ? (
          <GlassPanel padding="lg" className="rise">
            <EmptyState
              icon="checkCircle"
              title="This item has left today's briefing"
              text="It was handled, snoozed or no longer applies. Everything still open is on Today."
              actions={
                <ButtonLink href="/today" variant="secondary" iconLeft="arrowLeft">
                  Back to Today
                </ButtonLink>
              }
            />
          </GlassPanel>
        ) : (
          <ErrorBlock error={query.error} what="This item" onRetry={() => void query.refetch()} />
        )}
      </Page>
    );
  }

  const { item, explanation } = query.data;
  const rec = item.recommendation;
  const due = dueText(item, now, zone);
  // When the briefing is worded live, the validated sentence already carries the step and its
  // reason, so it stands alone. Otherwise the step is the headline and the rule's reason follows.
  const phrased = rec && rec.text_source === "llm" && rec.text ? rec.text : null;
  const step = rec ? (phrased ?? rec.display_text ?? rec.label) : null;
  const because = rec && !phrased ? rec.reason_text : null;
  const effect = rec?.effect_text ?? null;

  const facts: Fact[] = [
    { label: "Kind", value: kindLabel(item), icon: "tag" },
    { label: "Group", value: SECTION_LABEL[item.section], icon: "layers" },
    { label: "Due", value: due ? <span className={item.overdue ? "text-ember-text" : undefined}>{due}</span> : "No deadline", icon: "clock" },
    { label: "Last change", value: item.fact_at ? <DateText value={item.fact_at} style="dayTime" /> : null, icon: "history" },
    ...(item.on_behalf_of ? [{ label: "On behalf of", value: item.on_behalf_of.display_name, icon: "user" as const }] : []),
  ];

  return (
    <Page>
      <RecordHeader
        breadcrumb={[...CRUMBS, { label: item.title }]}
        title={item.title}
        status={
          <>
            <Badge tone={itemTone(item)} dot>
              {item.overdue ? "Overdue" : (SECTION_LABEL[item.section] ?? "In today's briefing")}
            </Badge>
            {item.change_kind === "new" ? <Badge tone="gold">New</Badge> : null}
            {item.change_kind === "changed" ? <Badge tone="cobalt">Changed</Badge> : null}
          </>
        }
        lead={item.summary_text ? <span className="lk-tnum">{item.summary_text}</span> : undefined}
        facts={<FactStrip items={facts} />}
        actions={<ItemActions item={item} commands={commands} emphasis hideExplain />}
      />

      {commands.disabledReason ? <p className="t-body-sm text-amber-text">{commands.disabledReason}</p> : null}

      <Split
        main={
          <>
            {rec ? (
              <GlassPanel as="section" padding="lg" eyebrow="Suggested next step" className="rise" style={riseAt(1)}>
                <div className="flex flex-col gap-5">
                  <p className="t-display-sm text-ink max-w-[40ch]">{step}</p>
                  {because ? <p className="t-body-lg text-ink-2 max-w-[60ch]">{because}</p> : null}
                  {effect || rec.alternatives.length > 0 ? (
                    <dl className="m-0 grid gap-5 sm:grid-cols-2">
                      {effect ? (
                        <div className="flex flex-col gap-1">
                          <dt className="t-overline text-ink-3">What it changes</dt>
                          <dd className="t-body text-ink m-0">{effect}</dd>
                        </div>
                      ) : null}
                      {rec.alternatives.length > 0 ? (
                        <div className="flex flex-col gap-1">
                          <dt className="t-overline text-ink-3">Or instead</dt>
                          <dd className="t-body text-ink m-0">
                            <ul className="m-0 flex list-none flex-col gap-1 p-0">
                              {rec.alternatives.map((alternative) => (
                                <li key={alternative}>{alternative}</li>
                              ))}
                            </ul>
                          </dd>
                        </div>
                      ) : null}
                    </dl>
                  ) : null}
                </div>
              </GlassPanel>
            ) : null}

            <GlassPanel as="section" padding="lg" eyebrow="Why it is here" className="rise" style={riseAt(2)}>
              <div className="flex flex-col gap-4">
                {explanation.reasons.length > 0 ? (
                  <ul className="m-0 flex list-none flex-col gap-3 p-0">
                    {explanation.reasons.map((reason) => (
                      <li key={reason} className="t-body-lg text-ink flex items-start gap-3">
                        <span className="text-ink-3 mt-1.5 flex flex-none">
                          <Icon name="check" size={16} />
                        </span>
                        {reason}
                      </li>
                    ))}
                  </ul>
                ) : null}
                <p className={explanation.reasons.length > 0 ? "t-body-sm text-ink-2 max-w-[72ch]" : "t-body-lg text-ink max-w-[68ch]"}>{explanation.text}</p>
                {explanation.rule_version ? <p className="t-caption text-ink-3">Rule version {explanation.rule_version}</p> : null}
              </div>
            </GlassPanel>
          </>
        }
        aside={
          <>
            <GlassPanel as="section" padding="md" eyebrow="Evidence" className="rise" style={riseAt(3)}>
              {explanation.sources.length === 0 ? (
                <p className="t-body-sm text-ink-3">This item does not cite a record.</p>
              ) : (
                <ul className="m-0 flex list-none flex-col p-0">
                  {explanation.sources.map((source) => (
                    <li key={`${source.type}:${source.id}`} className="border-line flex flex-col gap-1 border-t py-3 first:border-t-0 first:pt-0 last:pb-0">
                      <span className="t-caption text-ink-3">{typeWord(source.type)}</span>
                      {source.href ? (
                        <TextLink href={source.href as Route} className="t-h4">
                          {source.label}
                        </TextLink>
                      ) : (
                        <span className="t-h4 text-ink">{source.label}</span>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </GlassPanel>

            {item.uncertainty_flags.length > 0 ? (
              <GlassPanel as="section" padding="md" eyebrow="Check before you rely on it" className="rise" style={riseAt(4)}>
                <ul className="m-0 flex list-none flex-col gap-2 p-0">
                  {item.uncertainty_flags.map((flag) => (
                    <li key={flag.code} className="t-body-sm text-ink flex items-start gap-2">
                      <span className="text-amber-text flex flex-none">
                        <Icon name="alert" size={16} />
                      </span>
                      {uncertaintyText(flag)}
                    </li>
                  ))}
                </ul>
              </GlassPanel>
            ) : null}
          </>
        }
      />

      <ItemDialogs commands={commands} showDetailsLink={false} />
    </Page>
  );
}
