"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { ComboBox } from "@/components/ui/select";
import { api, requestUntyped } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { useDebouncedValue } from "@/lib/hooks";

interface PeopleResult {
  groups: { resource_type: string; hits: { resource_id: string; title: string; subtitle: string | null }[] }[];
}

/** Colleague picker over the people directory search (name and title only, never contact details). */
export function PeoplePicker({ label, value, onChange, errorMessage }: { label: string; value: string | null; onChange: (userId: string | null) => void; errorMessage?: string }) {
  const [text, setText] = useState("");
  const q = useDebouncedValue(text.trim(), 250);
  const query = useQuery({
    queryKey: [...queryKeys.search.query(q), "people"],
    queryFn: ({ signal }) =>
      requestUntyped<PeopleResult>(api, "get", "/api/v1/search", { params: { query: { q, types: "org.person", limit: 10 } }, signal }),
    enabled: q.length >= 2,
  });
  const hits = query.data?.groups.flatMap((g) => g.hits) ?? [];
  return (
    <ComboBox
      label={label}
      placeholder="Type at least two letters of a name"
      options={hits.map((h) => ({ id: h.resource_id, label: h.title, detail: h.subtitle ?? undefined }))}
      value={value}
      onChange={onChange}
      inputValue={text}
      onInputChange={setText}
      emptyText={q.length < 2 ? "Type at least two letters" : "No one by that name"}
      errorMessage={errorMessage}
    />
  );
}
