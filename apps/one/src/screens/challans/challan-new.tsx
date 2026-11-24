"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { createChallan } from "@/features/challans/api";
import { createBody, EMPTY_HEADER, fieldErrorsFrom, headerProblems, type HeaderForm } from "@/features/challans/form-model";
import { problemDescription } from "@/features/sales/use-quote-command";
import { commandSignature, createCommandKeys } from "@/lib/api/command-keys";
import { queryKeys } from "@/lib/api/query-keys";
import { useOnline } from "@/lib/hooks";
import { useSession } from "@/lib/session/context";
import { asRoute, CHALLANS_HOME } from "~/data/challans";
import { Page, PageHeader } from "~/shell/page";
import { NotPermitted } from "~/shell/states";
import { Banner, Button, ButtonLink, FormActions, toast } from "~/ui";
import { HeaderFields } from "./header-fields";
import { viewHref } from "./views";

const NO_DESTINATION = "Say where it is going. Choose one from your records or type the name.";

/**
 * Start a challan. Only the destination is needed; the server gives the draft its number and the
 * record opens on its lines, which is where the items go in.
 */
export function ChallanNew() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const online = useOnline();
  const { permissionKeys } = useSession();
  const [form, setForm] = useState<HeaderForm>(EMPTY_HEADER);
  const [submitted, setSubmitted] = useState(false);
  const [pending, setPending] = useState(false);
  const [serverErrors, setServerErrors] = useState<Record<string, string>>({});
  const [failure, setFailure] = useState<string | null>(null);
  const [commandKeys] = useState(() => createCommandKeys());

  if (!permissionKeys.has("challans.challan.create")) {
    return (
      <Page width="narrow">
        <PageHeader
          breadcrumb={[{ label: "Operations", href: "/operations" }, { label: "Challans", href: CHALLANS_HOME }, { label: "New" }]}
          title="New challan"
        />
        <NotPermitted what="Creating challans" />
      </Page>
    );
  }

  const problems = headerProblems(form);
  const errors: Record<string, string> = {
    ...serverErrors,
    ...(submitted && problems.destination_party ? { destination_party: NO_DESTINATION } : {}),
  };
  const fieldProblem = Object.values(errors).some(Boolean);

  const change = (next: HeaderForm) => {
    setForm(next);
    if (Object.keys(serverErrors).length > 0) setServerErrors({});
  };

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitted(true);
    if (Object.keys(problems).length > 0 || pending || !online) return;
    const body = createBody(form);
    const signature = commandSignature("create_challan", JSON.stringify(body));
    const attempt = commandKeys.attempt(signature, () => body);
    setPending(true);
    setServerErrors({});
    setFailure(null);
    try {
      const challan = await createChallan(attempt.payload, attempt.key);
      commandKeys.settle(signature);
      queryClient.setQueryData(queryKeys.challans.challan(challan.id), challan);
      await queryClient.invalidateQueries({ queryKey: ["challans", "list"] });
      await queryClient.invalidateQueries({ queryKey: ["challans", "summary"] });
      toast.success(`Draft ${challan.challan_number} created`, { description: "Add its lines next." });
      router.push(asRoute(viewHref(challan.path, "lines")));
    } catch (error) {
      commandKeys.settle(signature, error);
      const fields = fieldErrorsFrom(error);
      setServerErrors(fields);
      setFailure(Object.keys(fields).length > 0 ? null : (problemDescription(error) ?? "The connection dropped before the server answered. Check your network and try again."));
    } finally {
      setPending(false);
    }
  };

  return (
    <Page width="narrow">
      <PageHeader
        breadcrumb={[{ label: "Operations", href: "/operations" }, { label: "Challans", href: CHALLANS_HOME }, { label: "New" }]}
        title="New challan"
        lead="Say what is moving and where it is going. The draft gets its number when you create it, and the lines go in next."
      />

      {!online ? (
        <Banner tone="amber" title="You are offline.">
          The draft can be created once the connection is back.
        </Banner>
      ) : null}
      {failure ? (
        <Banner tone="ember" title="The draft was not created.">
          {failure}
        </Banner>
      ) : null}
      {fieldProblem ? (
        <Banner tone="ember" title="The draft was not created.">
          Check the fields marked below, then create it again.
        </Banner>
      ) : null}

      <form onSubmit={submit} className="stack" noValidate>
        <HeaderFields form={form} onChange={change} errors={errors} />
        <FormActions note="Nothing is issued yet. You can change the draft until you issue it.">
          <ButtonLink href={CHALLANS_HOME} variant="ghost">
            Cancel
          </ButtonLink>
          <Button type="submit" loading={pending} isDisabled={!online}>
            Create draft
          </Button>
        </FormActions>
      </form>
    </Page>
  );
}
