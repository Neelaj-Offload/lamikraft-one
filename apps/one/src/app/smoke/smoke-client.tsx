"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";

export function SmokeClient() {
  const health = useQuery({
    queryKey: ["smoke", "health"],
    queryFn: async () => {
      const response = await fetch("/api/v1/health/live");
      return response.status;
    },
  });
  return (
    <p className="t-code lk-mono mt-4">
      api client: {typeof api} · health: {health.isPending ? "…" : String(health.data ?? health.error)}
    </p>
  );
}
