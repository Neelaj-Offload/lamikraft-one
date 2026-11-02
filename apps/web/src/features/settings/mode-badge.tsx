import { Badge, DemoBadge, NotConnectedBadge } from "@/components/ui/badge";
import type { IntegrationMode } from "@/lib/session/types";
import { settingsMessages as m } from "@/messages/settings";

/** Demo, Not connected or Live, always as text plus colour. */
export function ModeBadge({ mode }: { mode: IntegrationMode }) {
  if (mode === "demo") return <DemoBadge />;
  if (mode === "not_connected") return <NotConnectedBadge />;
  return <Badge tone="success">{m.hub.live}</Badge>;
}
