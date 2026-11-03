import type { Metadata } from "next";
import { SimulatorScreen } from "../../_lib/roles";

export const metadata: Metadata = { title: "Role simulator · Settings" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** The member (``?user=``) or role (``?role=``) being explained lives in the URL. */
export default async function SimulatePage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const params = await searchParams;
  const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v) ?? null;
  const user = one(params.user);
  const role = one(params.role);
  return <SimulatorScreen key={`${user}|${role}`} userId={user && UUID.test(user) ? user : null} roleId={role && UUID.test(role) ? role : null} />;
}
