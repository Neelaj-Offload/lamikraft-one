"use client";

import { useQuery } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { Link, LinkButton } from "@/components/ui/link";
import { PageHeader } from "@/components/ui/page-header";
import { SectionCard } from "@/components/ui/section-card";
import { EmptyState, ErrorState, Loading } from "@/components/ui/states";
import { ProblemError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { briefingMessages as m } from "@/messages/briefing";
import { parseBriefingItem, parseExplanation } from "./parse";
import { fetchItemDetail } from "./slice3-api";

/**
 * One briefing item as a page (route `today-item`): the Explain dialog's content, deep-linkable. The server answers
 * only for an item of the member's current briefing that they can still see; anything else is "not found".
 */
export function ItemPageView({ issueId }: { issueId: string }) {
  const query = useQuery({
    queryKey: queryKeys.briefings.item(issueId),
    queryFn: async ({ signal }) => {
      const raw = await fetchItemDetail(issueId, signal);
      return { item: parseBriefingItem(raw.item), explanation: parseExplanation(raw.explanation), version: raw.version };
    },
    retry: (count, error) => !(error instanceof ProblemError && error.status === 404) && count < 2,
  });

  if (query.isPending) return <Loading label="the item" />;
  if (query.isError) {
    if (query.error instanceof ProblemError && query.error.status === 404) {
      return (
        <EmptyState title={m.itemPage.notFound} action={<LinkButton href="/today">{m.itemPage.back}</LinkButton>}>
          {m.itemPage.title}
        </EmptyState>
      );
    }
    return <ErrorState error={query.error} what="the item" onRetry={() => void query.refetch()} />;
  }
  const { item, explanation } = query.data;
  const rec = item.recommendation;
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow={m.status[item.family] ?? m.status.fallback}
        title={item.title}
        intro={item.summary_text ?? undefined}
        actions={<LinkButton href="/today">{m.itemPage.back}</LinkButton>}
      />
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="neutral">{m.sections[item.section]}</Badge>
        {item.due_label ? <Badge tone={item.overdue ? "danger" : "neutral"}>{item.due_label}</Badge> : null}
        {item.uncertainty_flags.map((flag) => (
          <Badge key={flag.code} tone="warning">
            {flag.label ?? flag.code}
          </Badge>
        ))}
      </div>
      {rec ? (
        <SectionCard title={m.itemPage.recommendation}>
          <p className="text-ink">{rec.text ?? rec.label}</p>
          {rec.text_source === "template" && rec.text ? null : rec.effect_text ? <p className="mt-1 text-sm text-ink-muted">{rec.effect_text}</p> : null}
        </SectionCard>
      ) : null}
      <SectionCard title={m.itemPage.explanation} description={explanation.rule_version ? m.itemPage.rule(explanation.rule_version) : undefined}>
        <p className="text-ink">{explanation.text}</p>
        {explanation.reasons.length > 0 ? (
          <ul className="mt-3 list-disc ps-5 text-sm text-ink-muted">
            {explanation.reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        ) : null}
      </SectionCard>
      {explanation.sources.length > 0 ? (
        <SectionCard title={m.itemPage.evidence}>
          <ul className="flex flex-col gap-2">
            {explanation.sources.map((source) => (
              <li key={`${source.type}:${source.id}`} className="flex flex-wrap items-baseline gap-x-2">
                <span className="text-sm text-ink-muted">{source.type.split(".").pop()?.replaceAll("_", " ")}</span>
                {source.href ? <Link href={source.href}>{source.label}</Link> : <span>{source.label}</span>}
              </li>
            ))}
          </ul>
        </SectionCard>
      ) : null}
    </div>
  );
}
