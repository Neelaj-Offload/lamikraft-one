"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { startImport, type ImportType } from "@/features/imports/api";
import { ProblemError } from "@/lib/api/errors";
import { invalidationMap } from "@/lib/api/query-keys";
import { formatCount } from "@/lib/format/money";
import { useSession } from "@/lib/session/context";
import { IMPORTS_RUN, useImportTypes } from "~/data/settings-data";
import { Page, PageHeader } from "~/shell/page";
import { ErrorBlock, NotPermitted } from "~/shell/states";
import { Banner, Button, ButtonLink, FileField, FormActions, FormSection, RadioCards, SkeletonText, toast } from "~/ui";
import { IMPORTS_CRUMBS, importTypeLabel } from "./imports-shared";
import { asRoute } from "./shared";

/**
 * Start an import: choose what the sheet holds, then hand over the file. Uploading only reads the
 * file and shows a preview; nothing reaches the catalogue until the import is reviewed and committed.
 */

function uploadProblem(error: unknown): string {
  if (error instanceof ProblemError && error.status === 415) return "Only CSV or XLSX files can be imported. Save the sheet in one of those formats and upload it again.";
  if (error instanceof ProblemError && error.status === 413) return "The file is larger than 50 MB. Split it into smaller sheets and import them one by one.";
  if (error instanceof ProblemError) return error.detail ?? error.title;
  return "The upload did not finish. Check your connection and try again.";
}

export function ImportNew() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { permissionKeys, zone } = useSession();
  const canRun = permissionKeys.has(IMPORTS_RUN);
  const types = useImportTypes(canRun);
  const [importType, setImportType] = useState<ImportType>("category_taxonomy");
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);

  const start = useMutation({
    mutationFn: (chosen: File) => startImport(importType, chosen),
    onSuccess: (detail) => {
      for (const key of invalidationMap["imports.changed"]) void queryClient.invalidateQueries({ queryKey: key });
      router.push(asRoute(detail.path));
    },
    onError: (error) => toast.error("The file was not uploaded", { description: uploadProblem(error) }),
  });

  const header = (
    <PageHeader breadcrumb={IMPORTS_CRUMBS} title="Start an import" lead="Choose what the sheet holds, then upload it. You map and check every row before anything is written." />
  );

  if (!canRun) {
    return (
      <Page width="reading">
        {header}
        <NotPermitted what="Starting an import" icon="upload" />
      </Page>
    );
  }

  const selected = types.data?.find((type) => type.import_type === importType);
  const submit = () => {
    if (!file) {
      setFileError("Choose a CSV or XLSX file to upload.");
      return;
    }
    setFileError(null);
    start.mutate(file);
  };

  return (
    <Page width="reading">
      {header}
      <form
        className="stack"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <FormSection title="What does the sheet hold?" description="They are listed in the order that works best: each one can refer to the ones above it.">
          <div className="col-span-full">
            {types.isPending ? (
              <SkeletonText lines={6} />
            ) : types.isError ? (
              <ErrorBlock error={types.error} what="The import types" onRetry={() => void types.refetch()} />
            ) : (
              <RadioCards
                label="Import type"
                hideLabel
                orientation="vertical"
                value={importType}
                onChange={(value) => setImportType(value as ImportType)}
                options={types.data.map((type, index) => {
                  const needs = type.depends_on.length ? `Needs ${type.depends_on.map((dependency) => importTypeLabel(dependency).toLowerCase()).join(" and ")}. ` : "";
                  const now = Object.entries(type.dependency_status)
                    .map(([name, count]) => `${formatCount(count, zone.locale)} ${name.replace(/_/g, " ")}`)
                    .join(", ");
                  return {
                    value: type.import_type,
                    label: `${index + 1}. ${importTypeLabel(type.import_type)}`,
                    description: (
                      <>
                        {type.description}
                        {needs || now ? (
                          <span className="t-caption mt-1 block text-ink-3">
                            {needs}
                            {now ? `You have ${now} today.` : ""}
                          </span>
                        ) : null}
                      </>
                    ),
                  };
                })}
              />
            )}
          </div>
        </FormSection>

        <FormSection title="The file" description="A CSV or XLSX file. Column names do not have to match exactly; you map them on the next screen.">
          {selected ? (
            <div className="col-span-full flex min-w-0 flex-col gap-3">
              <p className="t-label text-ink">Columns for {importTypeLabel(selected.import_type).toLowerCase()}</p>
              <ul className="flex list-none flex-wrap gap-2" aria-label="Expected columns">
                {selected.fields.map((field) => (
                  <li key={field.name} className="t-code-sm lk-mono rounded-sm border border-line bg-surface px-2 py-1">
                    {field.name}
                    {field.required ? <span className="text-ember-text"> required</span> : null}
                  </li>
                ))}
              </ul>
              <div>
                <ButtonLink external href={selected.template_path} download variant="secondary" size="sm" iconLeft="download">
                  Download the template
                </ButtonLink>
              </div>
            </div>
          ) : null}
          <FileField
            className="col-span-full"
            label="Spreadsheet"
            accept={[".csv", ".xlsx"]}
            onSelect={(files) => {
              setFile(files[0] ?? null);
              if (files[0]) setFileError(null);
            }}
            error={fileError ?? undefined}
            isDisabled={start.isPending}
          />
          <div className="col-span-full">
            <Banner tone="cobalt" icon="shield">
              Uploading only reads the file. Your catalogue changes when you commit, after the review.
            </Banner>
          </div>
        </FormSection>

        <FormActions note={file ? <span className="[overflow-wrap:anywhere]">{file.name}</span> : "No file chosen yet"}>
          <ButtonLink href="/settings/imports" variant="ghost">
            Cancel
          </ButtonLink>
          <Button type="submit" iconRight="arrowRight" loading={start.isPending}>
            Upload and preview
          </Button>
        </FormActions>
      </form>
    </Page>
  );
}

