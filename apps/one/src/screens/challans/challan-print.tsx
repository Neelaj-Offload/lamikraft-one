"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchChallanPrint } from "@/features/challans/api";
import type { ChallanPrint as PrintDocument, PrintParty } from "@/features/challans/types";
import { queryKeys } from "@/lib/api/query-keys";
import { asRoute, CHALLANS_HOME } from "~/data/challans";
import { ErrorBlock, LoadingBlock } from "~/shell/states";
import { Badge, Banner, Button, ButtonLink, DateText, Qty } from "~/ui";
import { QuantityList } from "./parts";

/**
 * Print rules for this document only. The page box is A4 with print margins; on screen the sheet
 * sits on the ground like paper on a desk, with the toolbar above it. Colours are tokens, and the
 * sheet prints exactly as shown so it stays legible in either theme.
 */
const PRINT_CSS = `
.cp-desk { min-height: 100dvh; padding: var(--space-6) var(--space-4) var(--space-16); }
.cp-column { margin: 0 auto; width: 100%; max-width: 210mm; display: flex; flex-direction: column; gap: var(--space-5); }
.cp-sheet {
  position: relative; overflow: hidden; background: var(--surface); color: var(--ink);
  border: 1px solid var(--line); border-radius: var(--radius-md); box-shadow: var(--shadow-raised);
  padding: 14mm 12mm; display: flex; flex-direction: column; gap: 7mm; min-height: 297mm;
}
.cp-watermark {
  position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; pointer-events: none;
  font-family: var(--font-serif); font-size: 120px; line-height: 1; letter-spacing: 0.12em; text-transform: uppercase;
  color: var(--ink); opacity: 0.06; transform: rotate(-24deg); user-select: none;
}
.cp-rule { border-top: 1px solid var(--line-strong); }
.cp-block { border: 1px solid var(--line-strong); border-radius: var(--radius-sm); padding: 4mm; display: flex; flex-direction: column; gap: 1mm; break-inside: avoid; }
.cp-table { width: 100%; border-collapse: collapse; }
.cp-table th, .cp-table td { padding: 2.2mm 2mm; text-align: left; vertical-align: top; }
.cp-table thead th { border-top: 1px solid var(--line-strong); border-bottom: 1px solid var(--line-strong); }
.cp-table tbody td { border-bottom: 1px solid var(--line); }
.cp-table tbody tr { break-inside: avoid; }
.cp-table .cp-num { text-align: right; white-space: nowrap; }
.cp-table tfoot th, .cp-table tfoot td { border-bottom: 1px solid var(--line-strong); }
.cp-wrap { overflow-wrap: anywhere; }
.cp-signs { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8mm; margin-top: auto; padding-top: 12mm; break-inside: avoid; }
.cp-sign { border-top: 1px solid var(--line-control); padding-top: 2mm; margin-top: 14mm; }
@media (max-width: 640px) {
  .cp-sheet { padding: var(--space-6) var(--space-4); min-height: 0; gap: var(--space-5); }
  .cp-watermark { font-size: 64px; }
  .cp-scroll { overflow-x: auto; }
  .cp-scroll .cp-table { min-width: 560px; }
  .cp-signs { grid-template-columns: minmax(0, 1fr); gap: var(--space-6); }
}
@page { size: A4; margin: 12mm; }
@media print {
  .cp-desk { padding: 0; min-height: 0; }
  .cp-column { max-width: none; gap: 0; }
  .cp-screen { display: none !important; }
  .cp-sheet { border: 0; border-radius: 0; box-shadow: none; padding: 0; min-height: calc(297mm - 24mm); print-color-adjust: exact; -webkit-print-color-adjust: exact; }
  .cp-table thead { display: table-header-group; }
}
`;

/** The challan on paper, laid out for A4: the data the PDF is made from, never the internal note. */
export function ChallanPrint({ challanId }: { challanId: string }) {
  const query = useQuery({ queryKey: queryKeys.challans.print(challanId), queryFn: ({ signal }) => fetchChallanPrint(challanId, signal) });
  const back = asRoute(`${CHALLANS_HOME}/${encodeURIComponent(challanId)}`);
  return (
    <main id="main" className="cp-desk">
      <style>{PRINT_CSS}</style>
      <div className="cp-column">
        {query.isPending ? (
          <>
            <div className="cp-screen">
              <ButtonLink href={back} variant="ghost" iconLeft="arrowLeft">
                Back to the challan
              </ButtonLink>
            </div>
            <LoadingBlock lines={10} label="Loading the challan for print" />
          </>
        ) : query.isError ? (
          <>
            <ErrorBlock error={query.error} what="This challan" onRetry={() => void query.refetch()} />
            <div>
              <ButtonLink href={back} variant="secondary" iconLeft="arrowLeft">
                Back to the challan
              </ButtonLink>
            </div>
          </>
        ) : (
          <Sheet doc={query.data} back={back} />
        )}
      </div>
    </main>
  );
}

function PartyBlock({ block }: { block: PrintParty }) {
  const [name, ...rest] = block.lines;
  return (
    <section className="cp-block">
      <h2 className="t-overline text-ink-3">{block.title}</h2>
      {name ? <p className="t-h4 cp-wrap text-ink">{name}</p> : null}
      {rest.map((line, index) => (
        <p key={`${index}-${line}`} className="t-body-sm cp-wrap text-ink-2">
          {line}
        </p>
      ))}
    </section>
  );
}

function Sheet({ doc, back }: { doc: PrintDocument; back: ReturnType<typeof asRoute> }) {
  const meta: { label: string; value: React.ReactNode }[] = [
    { label: "Date", value: <DateText value={doc.challan_date} style="business" /> },
    { label: "Type", value: [doc.type_label, doc.return_label, doc.destination_label].join(" · ") },
    ...(doc.reference_no ? [{ label: "Reference", value: doc.reference_no }] : []),
    ...(doc.expected_return_date ? [{ label: "Expected back", value: <DateText value={doc.expected_return_date} style="business" /> }] : []),
  ];

  return (
    <>
      <div className="cp-screen flex min-w-0 flex-wrap items-center justify-between gap-3">
        <ButtonLink href={back} variant="ghost" iconLeft="arrowLeft">
          Back to the challan
        </ButtonLink>
        <Button iconLeft="printer" onPress={() => window.print()}>
          Print challan
        </Button>
      </div>
      {doc.not_configured.length > 0 ? (
        <Banner tone="amber" className="cp-screen" title="Your company details are not set up yet.">
          The letterhead is incomplete until they are filled in under Settings, Company.
        </Banner>
      ) : null}

      <article className="cp-sheet" aria-label={`Delivery challan ${doc.challan_number}`}>
        {doc.watermark ? (
          <p aria-hidden="true" className="cp-watermark">
            {doc.watermark}
          </p>
        ) : null}

        <header className="flex flex-wrap items-start justify-between gap-x-8 gap-y-4">
          <div className="flex min-w-0 flex-col gap-1">
            <p className="t-h3 cp-wrap text-ink">{doc.company_name}</p>
            {doc.company_lines.map((line, index) => (
              <p key={`${index}-${line}`} className="t-body-sm cp-wrap text-ink-2">
                {line}
              </p>
            ))}
          </div>
          <div className="flex min-w-0 flex-col items-start gap-1 sm:items-end sm:text-right">
            <h1 className="t-display-sm text-ink">Delivery challan</h1>
            <p className="t-code lk-mono text-ink">{doc.challan_number}</p>
          </div>
        </header>

        <dl className="cp-rule grid grid-cols-2 gap-x-6 gap-y-3 pt-4 sm:grid-cols-4">
          {meta.map((item) => (
            <div key={item.label} className="flex min-w-0 flex-col gap-0.5">
              <dt className="t-overline text-ink-3">{item.label}</dt>
              <dd className="t-body-sm cp-wrap lk-tnum text-ink">{item.value}</dd>
            </div>
          ))}
        </dl>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <PartyBlock block={doc.from_block} />
          <PartyBlock block={doc.to_block} />
        </div>

        <div className="cp-scroll">
          <table className="cp-table t-body-sm">
            <caption className="sr-only">Lines of delivery challan {doc.challan_number}</caption>
            <thead>
              <tr className="t-overline text-ink-3">
                <th scope="col" className="cp-num">
                  No.
                </th>
                <th scope="col">Code</th>
                <th scope="col">Item</th>
                <th scope="col">HSN/SAC</th>
                <th scope="col" className="cp-num">
                  Quantity
                </th>
                <th scope="col">Remarks</th>
              </tr>
            </thead>
            <tbody>
              {doc.lines.map((line) => (
                <tr key={line.line_no} className="text-ink">
                  <td className="cp-num lk-tnum text-ink-3">{line.line_no}</td>
                  <td className="lk-mono cp-wrap">{line.item_code ?? ""}</td>
                  <td className="cp-wrap">{line.item_name}</td>
                  <td className="lk-mono">{line.hsn_sac ?? ""}</td>
                  <td className="cp-num">
                    <Qty value={{ value: line.quantity, uom: line.unit }} />
                  </td>
                  <td className="cp-wrap text-ink-2">{line.remarks ?? ""}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <th scope="row" colSpan={4} className="cp-num t-label text-ink">
                  Total
                </th>
                <td className="cp-num t-label text-ink">
                  <QuantityList value={doc.total_quantity} className="justify-end" />
                </td>
                <td />
              </tr>
            </tfoot>
          </table>
        </div>

        {doc.remarks ? (
          <section className="flex flex-col gap-1">
            <h2 className="t-overline text-ink-3">Remarks</h2>
            <p className="t-body-sm cp-wrap whitespace-pre-line text-ink">{doc.remarks}</p>
          </section>
        ) : null}

        <section className="flex flex-col gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="t-overline text-ink-3">Terms</h2>
            {doc.terms_are_demo ? (
              <span className="cp-screen">
                <Badge tone="amber" size="sm">
                  Demo terms
                </Badge>
              </span>
            ) : null}
          </div>
          <ol className="t-body-sm m-0 flex list-decimal flex-col gap-1 ps-5 text-ink-2">
            {doc.terms.map((term, index) => (
              <li key={`${index}-${term}`} className="cp-wrap">
                {term}
              </li>
            ))}
          </ol>
          {doc.terms_are_demo ? <p className="t-caption cp-screen text-ink-3">Set your own terms under Settings, Company. Until then these demo terms are printed.</p> : null}
        </section>

        <section className="cp-signs" aria-label="Signatures">
          {doc.signatures.map((label) => (
            <div key={label} className="cp-sign t-caption text-ink-3">
              {label}
            </div>
          ))}
        </section>
      </article>
    </>
  );
}
