import type { Metadata } from "next";
import { UserDetailScreen } from "../../_lib/users";

export const metadata: Metadata = { title: "Member · Settings" };

export default async function UserPage({ params }: { params: Promise<{ userId: string }> }) {
  const { userId } = await params;
  return <UserDetailScreen userId={userId} />;
}
