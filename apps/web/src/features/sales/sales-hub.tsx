"use client";

import { Link, LinkButton } from "@/components/ui/link";
import { useSession } from "@/lib/session/context";
import { salesMessages as m } from "@/messages/sales";

const AREAS = [
  { href: "/sales/quotes", title: m.hub.quotes, hint: m.hub.quotesHint, permission: "sales.quote.read" },
  { href: "/sales/enquiries", title: m.hub.enquiries, hint: m.hub.enquiriesHint, permission: "sales.enquiry.read" },
  { href: "/sales/customer-messages", title: m.hub.messages, hint: m.hub.messagesHint, permission: "sales.customer_message.read" },
] as const;

/** The sales hub: the areas this role can read, and New quote when it may create one. */
export function SalesHub() {
  const { permissionKeys } = useSession();
  const areas = AREAS.filter((area) => permissionKeys.has(area.permission));
  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h1 className="text-[28px] font-bold tracking-tight md:text-3xl">{m.hub.title}</h1>
          <p className="text-ink-muted">{m.hub.intro}</p>
        </div>
        {permissionKeys.has("sales.quote.create") ? (
          <LinkButton href="/sales/quotes/new" variant="primary">
            {m.hub.newQuote}
          </LinkButton>
        ) : null}
      </header>
      <ul className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {areas.map((area) => (
          <li key={area.href} className="flex flex-col gap-1 rounded-lg border bg-surface p-4">
            <Link href={area.href} className="text-lg font-semibold">
              {area.title}
            </Link>
            <p className="text-sm text-ink-muted">{area.hint}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}
