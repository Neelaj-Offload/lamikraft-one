import type { Metadata } from "next";
import { userListStateFrom } from "../_lib/user-list-state";
import { UserListScreen } from "../_lib/users";

export const metadata: Metadata = { title: "Users · Settings" };

/** Members: search, status, role and page offset live in the URL. */
export default async function UsersPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const state = userListStateFrom(await searchParams);
  return <UserListScreen key={`${state.q}|${state.status}|${state.role}|${state.offset}`} state={state} />;
}
