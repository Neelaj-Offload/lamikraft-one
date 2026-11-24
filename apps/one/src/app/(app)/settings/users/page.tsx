import type { Metadata } from "next";
import { userListStateFrom } from "@/app/(app)/settings/_lib/user-list-state";
import { UsersList } from "~/screens/settings-access/users-list";

export const metadata: Metadata = { title: "People · Settings" };

/** Everyone who can sign in: search, status, role and the page offset live in the URL. */
export default async function UsersPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const state = userListStateFrom(await searchParams);
  return <UsersList key={`${state.q}|${state.status}|${state.role}|${state.offset}`} state={state} />;
}
