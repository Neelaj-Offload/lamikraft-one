"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { fetchChallan, updateChallanHeader } from "@/features/challans/api";
import { fieldErrorsFrom, headerChanges, headerFormOf, type HeaderForm } from "@/features/challans/form-model";
import type { ChallanDetail } from "@/features/challans/types";
import { useChallanCommand, type ChallanCommands } from "@/features/challans/use-challan-command";
import { useScreenContribution } from "@/features/assistant/screen-context-store";
import { queryKeys } from "@/lib/api/query-keys";
import { asRoute, CHALLANS_HOME, DESTINATION_PHRASE, isEditable, issueBlockedText, RETURN_LABEL, tracksReturns, TYPE_LABEL } from "~/data/challans";
import { Page, RecordHeader } from "~/shell/page";
import { ErrorBlock, LoadingBlock } from "~/shell/states";
import { Badge, Banner, Button, ButtonLink, DateText, Drawer, FactStrip, Menu, Skeleton, SkeletonText, Tabs, TextLink, type MenuItem } from "~/ui";
import { useChallanActions } from "./challan-actions";
import { HeaderFields } from "./header-fields";
import { AddLineDrawer, LinesView } from "./lines-view";
import { NoteView } from "./note-view";
import { QuantityList, StatusBadge } from "./parts";
import { ActivityView, DetailsView, Overview, ReturnsView } from "./record-views";
import { viewHref, type ChallanView } from "./views";

/** A challan: where it stands, its lines, its details, what came back, its history and the team's note. */
export function ChallanRecord({ challanId, view }: { challanId: string; view: ChallanView }) {
  const query = useQuery({ queryKey: queryKeys.challans.challan(challanId), queryFn: ({ signal }) => fetchChallan(challanId, signal) });
  if (query.isPending) {
    return (
      <Page>
        <div className="lk-glass record-head" role="status" aria-label="Loading the challan">
          <Skeleton width="140px" height={14} />
          <Skeleton width="45%" height={32} />
          <SkeletonText lines={2} />
        </div>
        <LoadingBlock lines={6} label="Loading the challan" />
      </Page>
    );
  }
  if (query.isError) {
    return (
      <Page>
        <ErrorBlock error={query.error} what="This challan" onRetry={() => void query.refetch()} />
        <div>
          <ButtonLink href={CHALLANS_HOME} variant="secondary" iconLeft="arrowLeft">
            All challans
          </ButtonLink>
        </div>
      </Page>
    );
  }
  return <Loaded challan={query.data} view={view} />;
}

function Loaded({ challan, view: asked }: { challan: ChallanDetail; view: ChallanView }) {
  const commands = useChallanCommand(challan.id);
  const actions = useChallanActions(challan, commands);
  const [editing, setEditing] = useState(false);
  const [adding, setAdding] = useState(false);
  const editable = isEditable(challan);
  const returns = tracksReturns(challan);
  const blocked = issueBlockedText(challan);
  const offline = Boolean(commands.offline);
  const path = challan.path;
  // A link to the Returns view of a challan that does not track returns falls back to the overview.
  const view: ChallanView = asked === "returns" && !returns ? "overview" : asked;

  useScreenContribution({ focus: { type: "challans.challan", id: challan.id, version: challan.version } });

  const menu: MenuItem[] = [...actions.menu];
  if (editable) {
    const edit: MenuItem[] = [{ id: "edit", label: "Edit details", icon: "edit", isDisabled: offline, onAction: () => setEditing(true) }];
    if (menu.length > 0) edit.push({ id: "sep-edit", separator: true });
    menu.unshift(...edit);
  }

  // The step forward leads; on a draft that cannot be issued yet, adding a line does.
  const primary = actions.forward ? (
    <Button iconLeft={actions.forward.action === "issue" ? "send" : "checkCircle"} loading={actions.pending === actions.forward.action} isDisabled={offline} onPress={actions.startForward}>
      {actions.forwardLabel}
    </Button>
  ) : editable ? (
    <Button iconLeft="plus" isDisabled={offline} onPress={() => setAdding(true)}>
      Add line
    </Button>
  ) : null;

  const typeLine = `${TYPE_LABEL[challan.challan_type] ?? challan.challan_type}, ${(RETURN_LABEL[challan.return_type] ?? challan.return_type).toLowerCase()}, ${DESTINATION_PHRASE[challan.destination_type] ?? challan.destination_type}`;

  return (
    <Page>
      <RecordHeader
        breadcrumb={[{ label: "Operations", href: "/operations" }, { label: "Challans", href: CHALLANS_HOME }, { label: challan.challan_number }]}
        code={challan.challan_number}
        title={challan.destination_party}
        status={
          <>
            <StatusBadge status={challan.status} />
            {challan.deleted_at ? <Badge tone="ember">Deleted</Badge> : null}
          </>
        }
        lead={
          <>
            {typeLine}
            {challan.original_challan ? (
              <>
                {" · against "}
                <TextLink href={asRoute(challan.original_challan.path)}>{challan.original_challan.challan_number}</TextLink>
              </>
            ) : null}
          </>
        }
        facts={
          <FactStrip
            items={[
              { label: "Challan date", icon: "calendar", value: <DateText value={challan.challan_date} style="business" /> },
              { label: "Quantity", icon: "boxes", value: <QuantityList value={challan.quantity_by_unit} /> },
              challan.return_type === "returnable"
                ? { label: "Expected back", icon: "undo", value: challan.expected_return_date ? <DateText value={challan.expected_return_date} style="business" /> : null }
                : { label: "Reference", icon: "hash", value: challan.reference_no },
              { label: "Owner", icon: "user", value: challan.owner.display_name },
            ]}
          />
        }
        actions={
          <>
            {primary}
            {actions.model.canExport ? (
              <ButtonLink href={asRoute(actions.printHref)} variant="secondary" iconLeft="printer">
                Print
              </ButtonLink>
            ) : null}
            {actions.model.canExport ? (
              <ButtonLink external href={actions.pdfHref} variant="ghost" iconLeft="download">
                PDF
              </ButtonLink>
            ) : null}
            {menu.length > 0 ? (
              <Menu
                label="More challan actions"
                items={menu}
                placement="bottom end"
                trigger={
                  <Button variant="secondary" iconRight="chevronDown">
                    More
                  </Button>
                }
              />
            ) : null}
          </>
        }
      >
        <Tabs
          label="Views of this challan"
          selectedKey={view}
          tabs={[
            { id: "overview", label: "Overview", href: asRoute(path) },
            { id: "lines", label: "Lines", count: challan.lines.length, href: asRoute(viewHref(path, "lines")) },
            { id: "details", label: "Details", href: asRoute(viewHref(path, "details")) },
            ...(returns ? [{ id: "returns", label: "Returns", count: challan.return_links.length, href: asRoute(viewHref(path, "returns")) }] : []),
            { id: "activity", label: "Activity", href: asRoute(viewHref(path, "activity")) },
            { id: "note", label: "Internal note", href: asRoute(viewHref(path, "note")) },
          ]}
        />
      </RecordHeader>

      {offline ? (
        <Banner tone="amber" title="You are offline.">
          You can read this challan. Changes are saved again once the connection is back.
        </Banner>
      ) : null}
      {challan.deleted_at ? (
        <Banner tone="ember" icon="trash" title="This draft was deleted.">
          Its number stays reserved and is never given to another challan.
        </Banner>
      ) : null}
      {blocked && view !== "lines" ? (
        <Banner
          tone="amber"
          title="Not ready to issue."
          action={
            <ButtonLink href={asRoute(viewHref(path, "lines"))} variant="secondary" size="sm">
              Go to lines
            </ButtonLink>
          }
        >
          {blocked}
        </Banner>
      ) : null}

      {view === "overview" ? <Overview challan={challan} /> : null}
      {view === "lines" ? <LinesView challan={challan} editable={editable} commands={commands} onAdd={() => setAdding(true)} /> : null}
      {view === "details" ? <DetailsView challan={challan} canEdit={editable} onEdit={() => setEditing(true)} /> : null}
      {view === "returns" ? <ReturnsView challan={challan} /> : null}
      {view === "activity" ? <ActivityView challan={challan} /> : null}
      {view === "note" ? <NoteView challanId={challan.id} /> : null}

      {editable ? (
        <>
          <EditDetailsDrawer key={`${challan.id}-${challan.version}-${editing}`} challan={challan} commands={commands} isOpen={editing} onClose={() => setEditing(false)} />
          <AddLineDrawer challan={challan} commands={commands} isOpen={adding} onClose={() => setAdding(false)} />
        </>
      ) : null}
      {actions.dialogs}
    </Page>
  );
}

/** Change the header of a draft: only the fields that changed are sent, with the version read. */
function EditDetailsDrawer({ challan, commands, isOpen, onClose }: { challan: ChallanDetail; commands: ChallanCommands; isOpen: boolean; onClose: () => void }) {
  const [base] = useState(() => headerFormOf(challan));
  const [form, setForm] = useState<HeaderForm>(base);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [missing, setMissing] = useState(false);
  const busy = commands.pending === "update_header";

  const save = async () => {
    if (!form.party && !form.destination_party.trim()) {
      setMissing(true);
      return;
    }
    const changes = headerChanges(base, form);
    if (Object.keys(changes).length === 0) {
      onClose();
      return;
    }
    const outcome = await commands.run("update_header", [JSON.stringify(changes)], (key, current) => updateChallanHeader(current, changes, key), {
      done: "Details saved",
      failed: "The details were not saved",
    });
    if (outcome.ok) onClose();
    else setErrors(fieldErrorsFrom(outcome.error));
  };

  const shown = { ...errors, ...(missing && !form.party && !form.destination_party.trim() ? { destination_party: "Say where it is going. Choose one from your records or type the name." } : {}) };

  return (
    <Drawer
      isOpen={isOpen}
      onOpenChange={(open) => (open || busy ? undefined : onClose())}
      width="lg"
      title="Edit details"
      description={`${challan.challan_number} · ${challan.destination_party}`}
      footer={
        <>
          <Button variant="ghost" onPress={onClose} isDisabled={busy}>
            Cancel
          </Button>
          <Button loading={busy} isDisabled={Boolean(commands.offline)} onPress={() => void save()}>
            Save details
          </Button>
        </>
      }
    >
      <form
        className="flex flex-col gap-8"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          if (!busy) void save();
        }}
      >
        <HeaderFields compact form={form} onChange={setForm} errors={shown} />
      </form>
    </Drawer>
  );
}
