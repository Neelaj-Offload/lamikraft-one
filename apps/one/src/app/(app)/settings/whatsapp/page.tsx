import type { Metadata } from "next";
import { WhatsAppScreen } from "~/screens/settings-ai/whatsapp-screen";
import { parseWhatsAppView } from "~/screens/settings-ai/views";

export const metadata: Metadata = { title: "WhatsApp · Settings" };

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

/** Use the assistant from WhatsApp; admins also see the connection, stuck messages and templates. */
export default async function SettingsWhatsAppPage({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  return <WhatsAppScreen view={parseWhatsAppView(params.view)} />;
}
