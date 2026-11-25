"use client";

import { useState, type ReactNode } from "react";
import type { BomRead, RoutingRead } from "@/features/production/api";
import { versionStatus } from "~/data/production";
import { RecordHeader } from "~/shell/page";
import { Banner, Button, ConfirmDialog, DateText, FactStrip, ReasonDialog, type Fact } from "~/ui";
import { OPERATIONS_CRUMB, StatusBadge, versionLabel } from "./parts";

/**
 * The header shared by a bill of materials version and a routing version: what it is, who wrote
 * and approved it, and the three things that can happen to it (approve, retire, start the next
 * version). Each is offered only when the record's capabilities allow it.
 */
export function VersionHeader({
  record,
  list,
  countLabel,
  moreFacts = [],
  pending,
  offline,
  onApprove,
  onRetire,
  onCopy,
  children,
}: {
  record: BomRead | RoutingRead;
  list: { label: string; href: "/operations/production/boms" | "/operations/production/routings" };
  /** What `line_count` counts: "Components" or "Operations". */
  countLabel: string;
  moreFacts?: readonly Fact[];
  pending: string | null;
  offline: boolean;
  /** Each resolves true when the command went through. */
  onApprove: () => Promise<boolean>;
  onRetire: (reason: string) => Promise<boolean>;
  onCopy: () => void;
  children?: ReactNode;
}) {
  const [dialog, setDialog] = useState<null | "approve" | "retire">(null);
  const caps = record.capabilities;
  const name = versionLabel(record.version_no);
  const canApprove = Boolean(caps.approve?.allowed);
  const canRetire = Boolean(caps.retire?.allowed);
  const canCopy = Boolean(caps.new_version?.allowed);
  const settled = async (work: Promise<boolean>) => {
    if (!(await work)) throw new Error("not done");
  };

  return (
    <>
      <RecordHeader
        breadcrumb={[OPERATIONS_CRUMB, { label: list.label, href: list.href }, { label: `${record.product.product_key}, ${name.toLowerCase()}` }]}
        code={`${record.product.product_key} · ${name}`}
        title={record.product.name}
        status={<StatusBadge look={versionStatus(record.status)} />}
        lead={record.notes || undefined}
        facts={
          <FactStrip
            items={[
              { label: countLabel, icon: "list", value: String(record.line_count) },
              ...moreFacts,
              { label: "Written by", icon: "user", value: record.author?.display_name ?? null },
              {
                label: "Approved by",
                icon: "badgeCheck",
                value: record.approved_by?.display_name ? (
                  <>
                    {record.approved_by.display_name}
                    {record.approved_at ? (
                      <>
                        {", "}
                        <DateText value={record.approved_at} style="date" />
                      </>
                    ) : null}
                  </>
                ) : null,
              },
              { label: "Updated", icon: "clock", value: <DateText value={record.updated_at} style="dayTime" /> },
            ]}
          />
        }
        actions={
          canApprove || canRetire || canCopy ? (
            <>
              {canApprove ? (
                <Button iconLeft="badgeCheck" isDisabled={offline} onPress={() => setDialog("approve")}>
                  Approve version
                </Button>
              ) : null}
              {canCopy ? (
                <Button variant="secondary" iconLeft="copy" loading={pending === "copy"} isDisabled={offline} onPress={onCopy}>
                  Start new version
                </Button>
              ) : null}
              {canRetire ? (
                <Button variant="ghost" iconLeft="archive" isDisabled={offline} onPress={() => setDialog("retire")}>
                  Retire
                </Button>
              ) : null}
            </>
          ) : undefined
        }
      >
        {children}
      </RecordHeader>

      {offline ? (
        <Banner tone="amber" title="You are offline.">
          You can read this version. Actions work again once the connection is back.
        </Banner>
      ) : null}
      {record.status === "draft" && caps.approve?.reason_code === "separation_of_duties" ? (
        <Banner tone="cobalt" icon="users" title="You wrote this version.">
          Someone else has to approve it.
        </Banner>
      ) : null}

      <ConfirmDialog
        isOpen={dialog === "approve"}
        onOpenChange={(open) => setDialog(open ? "approve" : null)}
        title={`Approve ${name.toLowerCase()} for ${record.product.name}?`}
        description="New work orders will use this version. The approved version before it is retired. Work orders already planned keep the version they pinned."
        confirmLabel="Approve version"
        onConfirm={() => settled(onApprove())}
      />
      <ReasonDialog
        isOpen={dialog === "retire"}
        onOpenChange={(open) => setDialog(open ? "retire" : null)}
        tone="danger"
        title={`Retire ${name.toLowerCase()}?`}
        description="Work orders keep the version they pinned. A product with no approved version cannot be planned."
        reasonLabel="Why is it retired?"
        reasonHelp="Kept with the version for whoever looks at it later."
        confirmLabel="Retire version"
        cancelLabel="Keep it"
        onConfirm={(reason) => settled(onRetire(reason))}
      />
    </>
  );
}
