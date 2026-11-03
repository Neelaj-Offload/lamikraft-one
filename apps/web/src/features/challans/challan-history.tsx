"use client";

import { Badge } from "@/components/ui/badge";
import { LocalDateTime, Quantity } from "@/components/ui/format";
import { Link } from "@/components/ui/link";
import { SectionCard } from "@/components/ui/section-card";
import { challansMessages as m } from "@/messages/challans";
import type { ChallanDetail } from "./types";

const w = m.workspace;

/** Returns recorded against this challan (as the original) and made by it (as a Return challan): document links. */
export function ReturnLinks({ challan }: { challan: ChallanDetail }) {
  if (challan.return_links.length === 0 && challan.return_type !== "returnable" && challan.challan_type !== "return") return null;
  const unitOf = (lineId: string) => challan.lines.find((line) => line.id === lineId)?.unit ?? "";
  return (
    <SectionCard title={w.returnLinks}>
      {challan.return_links.length === 0 ? (
        <p className="text-ink-muted">—</p>
      ) : (
        <ul className="flex flex-col divide-y">
          {challan.return_links.map((link) => {
            const asOriginal = link.original_challan.id === challan.id;
            const other = asOriginal ? link.return_challan : link.original_challan;
            const unit = unitOf(asOriginal ? link.original_line_id : link.return_line_id);
            return (
              <li key={link.id} className="flex flex-wrap items-center justify-between gap-2 py-3 first:pt-0 last:pb-0">
                <span className="flex flex-col">
                  <Link href={other.path}>{asOriginal ? w.returnedOn(other.challan_number) : w.returnsAgainst(other.challan_number)}</Link>
                  <span className="text-sm text-ink-muted">
                    <LocalDateTime value={link.created_at} />
                  </span>
                </span>
                <span className="flex items-center gap-2">
                  {unit ? <Quantity value={{ value: link.quantity, uom: unit }} /> : <span className="tabular">{link.quantity}</span>}
                  {link.reversed_at ? <Badge>{m.status.cancelled}</Badge> : null}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </SectionCard>
  );
}

export function ChallanHistory({ challan }: { challan: ChallanDetail }) {
  const status = (code: string) => m.status[code] ?? code;
  return (
    <SectionCard title={w.history}>
      {challan.history.length === 0 ? (
        <p className="text-ink-muted">{w.noHistory}</p>
      ) : (
        <ol className="flex flex-col divide-y">
          {challan.history.map((entry, index) => (
            <li key={`${entry.occurred_at}-${index}`} className="flex flex-col gap-0.5 py-3 first:pt-0 last:pb-0">
              <span className="text-ink">{w.historyLine(status(entry.from_status), status(entry.to_status))}</span>
              <span className="text-sm text-ink-muted">
                <LocalDateTime value={entry.occurred_at} />
                {entry.actor?.display_name ? ` · ${entry.actor.display_name}` : null}
              </span>
              {entry.reason ? <span className="text-sm text-ink">{entry.reason}</span> : null}
            </li>
          ))}
        </ol>
      )}
    </SectionCard>
  );
}
