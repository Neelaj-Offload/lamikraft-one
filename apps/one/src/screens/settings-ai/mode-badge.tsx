import type { IntegrationMode } from "@/lib/session/types";
import { Badge } from "~/ui";

/**
 * How a connection runs: simulated ("Demo"), switched to live but not yet working ("Not
 * connected"), or live. Always a word, never colour alone.
 */
export function ModeBadge({ mode, size }: { mode: IntegrationMode; size?: "sm" }) {
  if (mode === "demo") {
    return (
      <Badge size={size} outline>
        Demo
      </Badge>
    );
  }
  if (mode === "not_connected") {
    return (
      <Badge size={size} tone="amber" dot>
        Not connected
      </Badge>
    );
  }
  return (
    <Badge size={size} tone="leaf" dot>
      Live
    </Badge>
  );
}
