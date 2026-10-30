"use client";

import { useQuery } from "@tanstack/react-query";
import { Link } from "@/components/ui/link";
import { ErrorState, Loading } from "@/components/ui/states";
import { queryKeys } from "@/lib/api/query-keys";
import { fetchCompleteness } from "./api";

/** Data completeness (UI-31, API-67, LP-11.2): per-rule counts of distinct live products, each a link to the
 * matching list filter, so the figure always equals the list it opens. */
export function CompletenessReport() {
  const query = useQuery({ queryKey: queryKeys.catalogue.completeness(), queryFn: ({ signal }) => fetchCompleteness(signal) });
  if (query.isPending) return <Loading label="completeness" />;
  if (query.isError) return <ErrorState error={query.error} what="the completeness report" onRetry={() => void query.refetch()} />;
  const data = query.data;
  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-[28px] font-bold tracking-tight md:text-3xl">Data completeness</h1>
        <p className="text-sm text-ink-muted tabular">
          {data.complete_products} of {data.total_products} live products pass every check.
        </p>
      </header>
      <table className="w-full text-sm">
        <caption className="sr-only">Completeness rules</caption>
        <thead>
          <tr className="border-b text-start">
            <th scope="col" className="py-2 text-start font-semibold">
              Check
            </th>
            <th scope="col" className="py-2 text-start font-semibold">
              Severity
            </th>
            <th scope="col" className="py-2 text-end font-semibold">
              Products
            </th>
          </tr>
        </thead>
        <tbody>
          {data.rules.map((rule) => (
            <tr key={rule.code} className="border-b">
              <th scope="row" className="py-2 text-start font-normal">
                {rule.label}
              </th>
              <td className="py-2 text-ink-muted">{rule.severity === "warning" ? "Needs attention" : "For information"}</td>
              <td className="py-2 text-end tabular">
                {rule.count ? <Link href={rule.filter_path}>{rule.count}</Link> : <span className="text-ink-muted">0</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {data.not_evaluated.length ? (
        <p className="text-sm text-ink-muted">Not evaluated for you: {data.not_evaluated.map((n) => `${n.code} (${n.reason})`).join(", ")}</p>
      ) : null}
    </div>
  );
}
