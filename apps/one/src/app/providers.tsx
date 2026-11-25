"use client";

import { domAnimation, LazyMotion, MotionConfig } from "motion/react";
import type { Route } from "next";
import { useRouter } from "next/navigation";
import type { ReactNode } from "react";
import { RouterProvider } from "react-aria-components";
import { useIsMotionReduced } from "@/lib/motion/use-motion-preference";
import { QueryProvider } from "@/lib/query";
import { motionTransition } from "~/lib/motion";

type AppRouter = ReturnType<typeof useRouter>;

declare module "react-aria-components" {
  interface RouterConfig {
    routerOptions: NonNullable<Parameters<AppRouter["push"]>[1]>;
  }
}

/** Client-side providers shared by every route: data cache, router bridge and motion settings. */
export function Providers({ children }: { children: ReactNode }) {
  const router = useRouter();
  const reduced = useIsMotionReduced();
  return (
    <QueryProvider>
      {/* React Aria links (menu items, tabs, breadcrumbs) navigate through the Next router. */}
      <RouterProvider navigate={(href, options) => router.push(href as Route, options)}>
        <LazyMotion features={domAnimation}>
          <MotionConfig reducedMotion={reduced ? "always" : "never"} transition={motionTransition.base}>
            {children}
          </MotionConfig>
        </LazyMotion>
      </RouterProvider>
    </QueryProvider>
  );
}
