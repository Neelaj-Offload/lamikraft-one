"use client";

import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { LocalDate, Quantity } from "@/components/ui/format";
import { Link } from "@/components/ui/link";
import { ErrorState, Loading, NotAvailable, PermissionDenied } from "@/components/ui/states";
import { ProblemError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { challansMessages as m } from "@/messages/challans";
import { fetchChallanPrint } from "./api";
import { QuantityList } from "./challan-bits";
import type { ChallanPrint } from "./types";

const p = m.print;

/** The browser print view (LM-92): the same data the PDF renders from, laid out for A4, never the internal note. */
export function ChallanPrintView({ challanId }: { challanId: string }) {
  const query = useQuery({ queryKey: queryKeys.challans.print(challanId), queryFn: ({ signal }) => fetchChallanPrint(challanId, signal) });
  if (query.isPending) return <Loading label={p.loading} variant="detail" />;
  if (query.isError) {
    const error = query.error;
    if (error instanceof ProblemError && error.status === 404) return <NotAvailable />;
    if (error instanceof ProblemError && error.status === 403) return <PermissionDenied area={p.loading} />;
    return <ErrorState error={error} what={p.loading} onRetry={() => void query.refetch()} />;
  }
  return <Document doc={query.data} challanId={challanId} />;
}

function Block({ heading, title, lines }: { heading: string; title: string; lines: readonly string[] }) {
  return (
    <section className="flex flex-col gap-1 rounded-md border p-3 print:rounded-none">
      <h2 className="text-xs font-semibold tracking-[0.08em] text-ink-muted uppercase">{heading}</h2>
      <p className="font-semibold text-ink">{title}</p>
      {lines.map((line, index) => (
        <p key={`${index}-${line}`} className="text-sm text-ink [overflow-wrap:anywhere]">
          {line}
        </p>
      ))}
    </section>
  );
}

function Document({ doc, challanId }: { doc: ChallanPrint; challanId: string }) {
  return (
    <article className="relative flex flex-col gap-5 bg-surface text-ink" aria-label={p.title(doc.challan_number)}>
      <div className="flex flex-wrap items-center justify-between gap-3 print:hidden">
        <Link href={`/operations/challans/${encodeURIComponent(challanId)}`}>{p.back}</Link>
        <Button variant="primary" onPress={() => window.print()}>
          {p.print}
        </Button>
      </div>
      {doc.watermark ? (
        <p aria-hidden="true" className="pointer-events-none absolute inset-x-0 top-1/3 text-center text-7xl font-bold tracking-[0.2em] text-ink-muted opacity-15 select-none">
          {doc.watermark}
        </p>
      ) : null}
      <header className="flex flex-wrap items-start justify-between gap-4 border-b pb-4">
        <div className="flex flex-col gap-0.5">
          <p className="text-lg font-bold">{doc.company_name}</p>
          {doc.company_lines.map((line, index) => (
            <p key={`${index}-${line}`} className="text-sm text-ink-muted">
              {line}
            </p>
          ))}
          {doc.not_configured.length ? <p className="text-sm text-warning-text print:hidden">{p.notConfigured}</p> : null}
        </div>
        <div className="flex flex-col items-end gap-0.5 text-end">
          <h1 className="text-2xl font-bold tracking-tight">{p.deliveryChallan}</h1>
          <p className="font-mono">{doc.challan_number}</p>
          <p className="text-sm">
            {p.date}: <LocalDate value={doc.challan_date} />
          </p>
          <p className="text-sm">
            {p.type}: {[doc.type_label, doc.return_label, doc.destination_label].join(" · ")}
          </p>
          {doc.reference_no ? (
            <p className="text-sm">
              {p.reference}: {doc.reference_no}
            </p>
          ) : null}
          {doc.expected_return_date ? (
            <p className="text-sm">
              {p.expectedReturn}: <LocalDate value={doc.expected_return_date} />
            </p>
          ) : null}
        </div>
      </header>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 print:grid-cols-2">
        <Block heading={doc.from_block.title} title={doc.from_block.lines[0] ?? ""} lines={doc.from_block.lines.slice(1)} />
        <Block heading={doc.to_block.title} title={doc.to_block.lines[0] ?? ""} lines={doc.to_block.lines.slice(1)} />
      </div>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <caption className="sr-only">{p.title(doc.challan_number)}</caption>
          <thead>
            <tr className="border-y text-start">
              <th scope="col" className="px-2 py-2 text-end">{p.columns.no}</th>
              <th scope="col" className="px-2 py-2 text-start">{p.columns.code}</th>
              <th scope="col" className="px-2 py-2 text-start">{p.columns.item}</th>
              <th scope="col" className="px-2 py-2 text-start">{p.columns.hsn}</th>
              <th scope="col" className="px-2 py-2 text-end">{p.columns.quantity}</th>
              <th scope="col" className="px-2 py-2 text-start">{p.columns.remarks}</th>
            </tr>
          </thead>
          <tbody>
            {doc.lines.map((line) => (
              <tr key={line.line_no} className="border-b align-top">
                <td className="px-2 py-2 text-end tabular">{line.line_no}</td>
                <td className="px-2 py-2 font-mono">{line.item_code ?? ""}</td>
                <td className="px-2 py-2 [overflow-wrap:anywhere]">{line.item_name}</td>
                <td className="px-2 py-2 font-mono">{line.hsn_sac ?? ""}</td>
                <td className="px-2 py-2 text-end">
                  <Quantity value={{ value: line.quantity, uom: line.unit }} />
                </td>
                <td className="px-2 py-2 [overflow-wrap:anywhere]">{line.remarks ?? ""}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <th scope="row" colSpan={4} className="px-2 py-2 text-end">
                {p.total}
              </th>
              <td colSpan={2} className="px-2 py-2 font-semibold">
                <QuantityList value={doc.total_quantity} />
              </td>
            </tr>
          </tfoot>
        </table>
      </div>
      {doc.remarks ? (
        <section className="flex flex-col gap-1">
          <h2 className="text-sm font-semibold">{p.remarks}</h2>
          <p className="whitespace-pre-line text-sm [overflow-wrap:anywhere]">{doc.remarks}</p>
        </section>
      ) : null}
      <section className="flex flex-col gap-1">
        <h2 className="text-sm font-semibold">{p.terms}</h2>
        <ol className="list-decimal ps-5 text-sm">
          {doc.terms.map((term, index) => (
            <li key={`${index}-${term}`}>{term}</li>
          ))}
        </ol>
        {doc.terms_are_demo ? <p className="text-xs text-ink-muted print:hidden">{p.demoTerms}</p> : null}
      </section>
      <section className="grid grid-cols-1 gap-4 pt-8 sm:grid-cols-3 print:grid-cols-3" aria-label={p.deliveryChallan}>
        {doc.signatures.map((label) => (
          <div key={label} className="flex min-h-20 flex-col justify-end border-t pt-2 text-sm text-ink-muted">
            {label}
          </div>
        ))}
      </section>
    </article>
  );
}
