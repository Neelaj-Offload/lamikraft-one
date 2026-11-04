"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button, unavailableWhen } from "@/components/ui/button";
import { LinkButton } from "@/components/ui/link";
import { toast } from "@/components/ui/toast";
import { problemDescription } from "@/features/sales/use-quote-command";
import { createIdempotencyKey } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { useOnline } from "@/lib/hooks";
import { useSession } from "@/lib/session/context";
import { ordersMessages as m } from "@/messages/orders";
import { convertQuote, fetchOrderForQuote } from "./api";

/**
 * "Convert to order" on a won quote, or a link to the order that already exists. Conversion is idempotent on the
 * server (one order per quote), so a double click or a retry lands on the same order.
 */
export function ConvertToOrder({ quoteId, status }: { quoteId: string; status: string }) {
  const { permissionKeys } = useSession();
  const router = useRouter();
  const queryClient = useQueryClient();
  const online = useOnline();
  const [key] = useState(() => createIdempotencyKey());
  const [pending, setPending] = useState(false);
  const canRead = permissionKeys.has("orders.sales_order.read");
  const existing = useQuery({
    queryKey: queryKeys.orders.forQuote(quoteId),
    queryFn: ({ signal }) => fetchOrderForQuote(quoteId, signal),
    enabled: status === "won" && canRead,
  });
  if (status !== "won") return null;
  if (existing.data) {
    return (
      <LinkButton href={existing.data.path} variant="secondary">
        {m.convert.open(existing.data.order_number)}
      </LinkButton>
    );
  }
  if (!permissionKeys.has("orders.sales_order.create") || existing.isPending) return null;
  return (
    <Button
      variant="primary"
      isPending={pending}
      {...unavailableWhen(online ? null : "You're offline.")}
      onPress={async () => {
        setPending(true);
        try {
          const result = await convertQuote(quoteId, key);
          toast.success(result.created ? m.convert.created(result.order.order_number) : m.convert.existing(result.order.order_number));
          await queryClient.invalidateQueries({ queryKey: queryKeys.orders.all() });
          router.push(result.order.path as Parameters<typeof router.push>[0]);
        } catch (error) {
          toast.error(m.convert.failed, { description: problemDescription(error) });
        } finally {
          setPending(false);
        }
      }}
    >
      {m.convert.action}
    </Button>
  );
}
