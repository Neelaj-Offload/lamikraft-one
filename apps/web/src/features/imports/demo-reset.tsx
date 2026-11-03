"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Button, unavailableWhen } from "@/components/ui/button";
import { TextField } from "@/components/ui/text-field";
import { toast } from "@/components/ui/toast";
import { ProblemError } from "@/lib/api/errors";
import { invalidationMap, queryKeys } from "@/lib/api/query-keys";
import { useSession } from "@/lib/session/context";
import { fetchDemoReset, runDemoReset } from "./api";

const REASON: Record<string, string> = {
  not_a_demo_company: "This is not a demo company; its data can never be cleared here.",
  demo_data_referenced: "Price lists, quotes or other records use the demo products; clear them first.",
};

/** Demo-only catalogue reset (LM-37, UI-88): shown only to holders of system.demo_data.delete; refused outside a demo
 * company; needs the typed phrase and a fresh preview token; the server re-checks everything. */
export function DemoResetPanel() {
  const { permissionKeys } = useSession();
  const queryClient = useQueryClient();
  const allowed = permissionKeys.has("system.demo_data.delete");
  const [phrase, setPhrase] = useState("");
  const preview = useQuery({ queryKey: queryKeys.imports.demoReset(), queryFn: ({ signal }) => fetchDemoReset(signal), enabled: allowed });
  const reset = useMutation({
    mutationFn: () => runDemoReset(preview.data?.token ?? "", phrase),
    onSuccess: (result) => {
      for (const key of invalidationMap["imports.changed"]) void queryClient.invalidateQueries({ queryKey: key });
      toast.success(`Demo catalogue cleared (${Object.values(result.deleted).reduce((a, b) => a + b, 0)} rows)`);
      setPhrase("");
    },
    onError: (error) =>
      toast.error(error instanceof ProblemError && error.code === "reauth_required" ? "Sign in again to confirm" : error instanceof ProblemError ? (error.detail ?? error.title) : "Not cleared"),
  });
  if (!allowed || !preview.data) return null;
  const p = preview.data;
  return (
    <section aria-label="Demo data" className="flex flex-col gap-3 rounded-md border border-dashed p-4">
      <h2 className="text-base font-semibold">Clear the demo catalogue</h2>
      <p className="text-sm text-ink-muted tabular">
        {Object.entries(p.counts)
          .map(([table, n]) => `${n} ${table.replace(/^catalogue_|^imports_/, "").replace(/_/g, " ")}`)
          .join(" · ")}
      </p>
      {p.allowed ? (
        <>
          <TextField label={`Type “${p.phrase}” to confirm`} value={phrase} onChange={setPhrase} />
          <div>
            <Button variant="danger" onPress={() => reset.mutate()} isPending={reset.isPending} {...unavailableWhen((phrase.trim() !== p.phrase) ? "Type the phrase exactly" : null)}>
              Clear demo catalogue
            </Button>
          </div>
        </>
      ) : (
        <p className="text-sm">{REASON[p.reason_code ?? ""] ?? "Not available."}</p>
      )}
    </section>
  );
}
