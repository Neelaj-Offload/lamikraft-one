"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { Route } from "next";
import { useMemo, useState } from "react";
import { useScreenContribution } from "@/features/assistant/screen-context-store";
import { closeEnquiry, fetchEnquiry } from "@/features/sales/api";
import { useResourceCommand } from "@/features/sales/resource-command";
import type { Enquiry } from "@/features/sales/types";
import { queryKeys } from "@/lib/api/query-keys";
import { useRecentRecord } from "@/lib/recent/recent-records";
import { useSession } from "@/lib/session/context";
import { Page, PageHeader, RecordHeader } from "~/shell/page";
import { ErrorBlock } from "~/shell/states";
import { Badge, Banner, Button, ButtonLink, DateText, FactStrip, GlassPanel, Icon, KeyValue, Modal, RadioGroup, Skeleton, SkeletonText, Tabs, TextLink } from "~/ui";
import { countryName, stagger } from "../customers/labels";
import { RecordActivity } from "../customers/record-collab";
import { Steps } from "../samples/steps";
import {
  CHANNEL_ICON,
  channelLabel,
  ENQUIRY_OUTCOMES,
  ENQUIRY_PIPELINE,
  ENQUIRY_STAGE_ICON,
  ENQUIRY_STAGE_LABEL,
  ENQUIRY_STAGE_TONE,
  OUTCOME_LABEL,
  type EnquiryView,
} from "./labels";

const CRUMBS = [
  { label: "Sales", href: "/sales" as Route },
  { label: "Enquiries", href: "/sales/enquiries" as Route },
];

export function EnquiryRecord({ enquiryId, view }: { enquiryId: string; view: EnquiryView }) {
  const query = useQuery({ queryKey: queryKeys.sales.enquiry(enquiryId), queryFn: ({ signal }) => fetchEnquiry(enquiryId, signal) });
  useRecentRecord("sales.enquiry", query.data?.id, query.isSuccess);
  useScreenContribution(query.data ? { focus: { type: "sales.enquiry", id: query.data.id, version: query.data.version } } : null);

  if (query.isPending) {
    return (
      <Page>
        <div className="lk-glass record-head" role="status" aria-label="Loading the enquiry">
          <Skeleton width={110} height={10} />
          <Skeleton width="45%" height={28} />
          <SkeletonText lines={2} />
        </div>
      </Page>
    );
  }
  if (query.isError) {
    return (
      <Page>
        <PageHeader breadcrumb={CRUMBS} title="Enquiry" />
        <ErrorBlock error={query.error} what="This enquiry" onRetry={() => void query.refetch()} />
      </Page>
    );
  }
  return <Loaded enquiry={query.data} view={view} />;
}

/** What should happen next, by stage. */
function standing(enquiry: Enquiry, canQuote: boolean): { title: string; text: string } {
  if (enquiry.status === "closed") {
    return { title: "This enquiry is closed", text: enquiry.outcome_code ? `Outcome: ${OUTCOME_LABEL[enquiry.outcome_code] ?? enquiry.outcome_code}.` : "Nothing more to do here." };
  }
  if (enquiry.quote_id) {
    return { title: "A quotation has gone out", text: `${enquiry.quote_number ?? "The quotation"} answers this enquiry. Follow it there; close the enquiry when the customer decides.` };
  }
  if (canQuote) {
    return { title: "Answer with a quotation", text: `${enquiry.party.display_name} is waiting for a price. Starting from here fills in the customer and links the quotation to this enquiry.` };
  }
  return { title: "Waiting for a quotation", text: "Someone with permission to quote needs to pick this up." };
}

function Loaded({ enquiry, view }: { enquiry: Enquiry; view: EnquiryView }) {
  const { permissionKeys } = useSession();
  const queryClient = useQueryClient();
  const keys = useMemo(() => [queryKeys.sales.enquiry(enquiry.id), ["sales", "enquiries"], ["sales", "enquiry-count"]], [enquiry.id]);
  const commands = useResourceCommand(`enquiry:${enquiry.id}`, keys);
  const [closing, setClosing] = useState(false);
  const [outcome, setOutcome] = useState<string | null>(null);

  const canClose = enquiry.allowed_transitions.some((transition) => transition.action === "close");
  const canQuote = enquiry.status !== "closed" && !enquiry.quote_id && permissionKeys.has("sales.quote.create");
  const canOpenCustomer = permissionKeys.has("parties.party.read");
  const base = `/sales/enquiries/${encodeURIComponent(enquiry.id)}`;
  const stageIndex = ENQUIRY_PIPELINE.indexOf(enquiry.status);
  const state = standing(enquiry, canQuote);
  const quoteHref = enquiry.quote_id ? (`/sales/quotes/${encodeURIComponent(enquiry.quote_id)}` as Route) : null;
  const customerHref = `/sales/parties/${encodeURIComponent(enquiry.party.id)}` as Route;

  const close = async () => {
    if (!outcome) return;
    const result = await commands.run("close", [enquiry.version, outcome], (key) => closeEnquiry(enquiry, outcome, key), {
      done: "Enquiry closed",
      failed: "The enquiry was not closed",
      conflictMessage: "This enquiry changed since you opened it. The latest version is showing.",
    });
    if (result.ok && result.value) queryClient.setQueryData(queryKeys.sales.enquiry(enquiry.id), result.value);
    if (result.ok || result.conflict) setClosing(false);
  };

  const primary = canQuote ? (
    <ButtonLink href={`/sales/quotes/new?enquiry=${encodeURIComponent(enquiry.id)}` as Route} iconLeft="filePlus">
      Create quotation
    </ButtonLink>
  ) : quoteHref ? (
    <ButtonLink variant="inverse" href={quoteHref} iconRight="arrowRight">
      Open quotation
    </ButtonLink>
  ) : null;

  return (
    <Page>
      <RecordHeader
        breadcrumb={[...CRUMBS, { label: enquiry.enquiry_number }]}
        code={enquiry.enquiry_number}
        title={enquiry.subject ?? `Enquiry from ${enquiry.party.display_name}`}
        status={
          <Badge tone={ENQUIRY_STAGE_TONE[enquiry.status]} dot>
            {ENQUIRY_STAGE_LABEL[enquiry.status]}
          </Badge>
        }
        facts={
          <FactStrip
            items={[
              { label: "From", value: canOpenCustomer ? <TextLink href={customerHref}>{enquiry.party.display_name}</TextLink> : enquiry.party.display_name, icon: "building" },
              { label: "Came by", value: channelLabel(enquiry.channel), icon: CHANNEL_ICON[enquiry.channel] ?? "message" },
              { label: "Received", value: <DateText value={enquiry.received_at} style="dayTime" />, icon: "calendar" },
              { label: "Looked after by", value: enquiry.owner.display_name, icon: "user" },
              { label: "Quotation", value: quoteHref ? <TextLink href={quoteHref}>{enquiry.quote_number ?? "Open"}</TextLink> : null, icon: "fileText" },
            ]}
          />
        }
        actions={
          <>
            {primary}
            {canClose ? (
              <Button variant="secondary" onPress={() => setClosing(true)} isDisabled={Boolean(commands.offline)}>
                Close enquiry
              </Button>
            ) : null}
          </>
        }
      >
        <Tabs
          label="Enquiry views"
          selectedKey={view}
          tabs={[
            { id: "overview", label: "Overview", href: base as Route },
            { id: "activity", label: "Activity", href: `${base}?view=activity` as Route },
          ]}
        />
      </RecordHeader>

      {commands.offline ? <Banner tone="amber" title="You are offline.">You can read this enquiry. Reconnect to close it.</Banner> : null}

      {view === "activity" ? (
        <RecordActivity resourceType="sales.enquiry" resourceId={enquiry.id} />
      ) : (
        <>
          <GlassPanel padding="lg" className="rise">
            <Steps
              label="Enquiry pipeline"
              current={stageIndex}
              complete={enquiry.status === "closed"}
              steps={ENQUIRY_PIPELINE.map((stage) => ({
                id: stage,
                label: ENQUIRY_STAGE_LABEL[stage],
                icon: ENQUIRY_STAGE_ICON[stage],
                caption:
                  stage === "received" ? (
                    <DateText value={enquiry.received_at} />
                  ) : stage === "assigned" && stageIndex >= 1 ? (
                    (enquiry.owner.display_name ?? undefined)
                  ) : stage === "quoted" && enquiry.quote_number ? (
                    <span className="lk-mono">{enquiry.quote_number}</span>
                  ) : stage === "closed" && enquiry.closed_at ? (
                    <DateText value={enquiry.closed_at} />
                  ) : undefined,
              }))}
            />
          </GlassPanel>

          <div className="split">
            <GlassPanel as="section" padding="lg" title="What they asked" titleAs="h2" className="rise flex flex-col gap-3" style={stagger(1)}>
              {enquiry.body ? (
                <>
                  {/* External text: rendered as plain text, never as markup or links. */}
                  <p className="t-body-lg whitespace-pre-wrap text-ink [overflow-wrap:anywhere]">{enquiry.body}</p>
                  <p className="t-caption flex items-center gap-2 text-ink-3">
                    <Icon name="shield" size={14} />
                    Written by the customer and shown as plain text. Links inside it are not clickable.
                  </p>
                </>
              ) : (
                <p className="t-body text-ink-3">The enquiry arrived without a message. The subject is all the customer sent.</p>
              )}
            </GlassPanel>

            <aside className="stack">
              <GlassPanel as="section" variant="strong" className="rise flex flex-col gap-3" style={stagger(2)} aria-label="Next step">
                <p className="t-overline text-gold-strong">{enquiry.status === "closed" ? "Outcome" : "Next step"}</p>
                <h2 className="t-display-sm">{state.title}</h2>
                <p className="t-body-sm text-ink-2">{state.text}</p>
              </GlassPanel>
              <GlassPanel as="section" title="Who is asking" titleAs="h2" className="rise" style={stagger(3)}>
                <KeyValue
                  rows
                  items={[
                    { label: "Customer", value: enquiry.party.display_name },
                    { label: "Number", value: enquiry.party.party_number, mono: true },
                    { label: "Country", value: countryName(enquiry.party.country_code) },
                  ]}
                />
                {canOpenCustomer ? (
                  <div className="mt-4">
                    <ButtonLink variant="secondary" size="sm" href={customerHref} iconRight="arrowRight">
                      Open their profile
                    </ButtonLink>
                  </div>
                ) : null}
              </GlassPanel>
            </aside>
          </div>
        </>
      )}

      {canClose ? (
        <Modal
          isOpen={closing}
          onOpenChange={setClosing}
          size="sm"
          title="Close this enquiry"
          description={`${enquiry.enquiry_number} leaves the open pipeline. Say how it ended so the team can see why.`}
          actions={
            <>
              <Button variant="ghost" onPress={() => setClosing(false)}>
                Keep it open
              </Button>
              <Button variant="inverse" loading={commands.pending === "close"} isDisabled={!outcome || Boolean(commands.offline)} onPress={() => void close()}>
                Close enquiry
              </Button>
            </>
          }
        >
          <RadioGroup label="How did it end" value={outcome ?? ""} onChange={setOutcome} options={ENQUIRY_OUTCOMES.map((code) => ({ value: code, label: OUTCOME_LABEL[code] ?? code }))} />
        </Modal>
      ) : null}
    </Page>
  );
}
