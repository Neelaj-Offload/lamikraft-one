"use client";

import type { Route } from "next";
import { useRouter } from "next/navigation";
import type { ReactNode } from "react";
import { RouterProvider } from "react-aria-components";
import { LiveAnnouncer, ToastRegion } from "@/components/ui/toast";
import { LkMotionConfig } from "@/lib/motion/motion-config";
import { QueryProvider } from "@/lib/query";

type AppRouter = ReturnType<typeof useRouter>;

declare module "react-aria-components" {
  interface RouterConfig {
    routerOptions: NonNullable<Parameters<AppRouter["push"]>[1]>;
  }
}

/** Client-side providers shared by every route. */
export function Providers({ children }: { children: ReactNode }) {
  const router = useRouter();
  return (
    <QueryProvider>
      {/* React Aria links (Menu items, Tabs, Breadcrumbs) navigate through the Next router. */}
      <RouterProvider navigate={(href, options) => router.push(href as Route, options)}>
        <LkMotionConfig>{children}</LkMotionConfig>
        <ToastRegion />
        <LiveAnnouncer />
      </RouterProvider>
    </QueryProvider>
  );
}
