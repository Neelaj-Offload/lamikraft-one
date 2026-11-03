"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Form } from "react-aria-components";
import { Button, unavailableWhen } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/page-header";
import { PermissionDenied } from "@/components/ui/states";
import { toast } from "@/components/ui/toast";
import { problemDescription } from "@/features/sales/use-quote-command";
import { commandSignature, createCommandKeys } from "@/lib/api/command-keys";
import { queryKeys } from "@/lib/api/query-keys";
import { useOnline } from "@/lib/hooks";
import { useSession } from "@/lib/session/context";
import { challansMessages as m } from "@/messages/challans";
import { createChallan } from "./api";
import { createBody, EMPTY_HEADER, fieldErrorsFrom, headerProblems, type HeaderForm } from "./form-model";
import { HeaderFields } from "./header-fields";

/** A new draft: the server allocates `DC-YYYY-NNNN` and the workspace opens on it (lines are added there). */
export function ChallanCreate() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const online = useOnline();
  const { permissionKeys } = useSession();
  const [form, setForm] = useState<HeaderForm>(EMPTY_HEADER);
  const [submitted, setSubmitted] = useState(false);
  const [pending, setPending] = useState(false);
  const [serverErrors, setServerErrors] = useState<Record<string, string>>({});
  const [commandKeys] = useState(() => createCommandKeys());
  if (!permissionKeys.has("challans.challan.create")) return <PermissionDenied area={m.create.permission} />;

  const problems = headerProblems(form);
  const errors: Record<string, string> = {
    ...serverErrors,
    ...(submitted && problems.destination_party ? { destination_party: m.create.destinationRequired } : {}),
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
    try {
      const challan = await createChallan(attempt.payload, attempt.key);
      commandKeys.settle(signature);
      queryClient.setQueryData(queryKeys.challans.challan(challan.id), challan);
      await queryClient.invalidateQueries({ queryKey: ["challans", "list"] });
      await queryClient.invalidateQueries({ queryKey: ["challans", "summary"] });
      toast.success(m.create.created(challan.challan_number));
      router.push(challan.path as Parameters<typeof router.push>[0]);
    } catch (error) {
      commandKeys.settle(signature, error);
      const fields = fieldErrorsFrom(error);
      setServerErrors(fields);
      toast.error(m.create.failed, { description: Object.keys(fields).length ? m.create.fixErrors : problemDescription(error) });
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <PageHeader title={m.create.title} intro={m.create.intro} eyebrow={m.area} />
      <Form onSubmit={submit} className="flex flex-col gap-6" validationBehavior="aria">
        <HeaderFields form={form} onChange={setForm} errors={errors} full />
        <div className="flex flex-wrap gap-3">
          <Button type="submit" variant="primary" isPending={pending} pendingLabel={m.create.creating} {...unavailableWhen(online ? null : m.offline)}>
            {m.create.submit}
          </Button>
        </div>
      </Form>
    </div>
  );
}
