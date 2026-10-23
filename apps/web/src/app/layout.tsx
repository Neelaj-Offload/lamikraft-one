import "@fontsource-variable/manrope";
// Devanagari faces are fetched only when Hindi text is rendered (unicode-range).
import "@fontsource/noto-sans-devanagari/400.css";
import "@fontsource/noto-sans-devanagari/600.css";
import "@fontsource/noto-sans-devanagari/700.css";
import "./globals.css";

import type { Metadata, Viewport } from "next";
import { cookies } from "next/headers";
import type { ReactNode } from "react";
import { htmlThemeAttributes, parseUiPreferences, UI_COOKIE } from "@/lib/ui-preferences";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: {
    default: "Lamikraft One",
    template: "%s · Lamikraft One",
  },
  description: "Crown / Lamikraft operations workspace.",
  applicationName: "Lamikraft One",
  robots: { index: false, follow: false },
  formatDetection: { telephone: false, email: false, address: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  colorScheme: "light dark",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f6f5f0" },
    { media: "(prefers-color-scheme: dark)", color: "#111613" },
  ],
};

export default async function RootLayout({ children }: { children: ReactNode }) {
  const preferences = parseUiPreferences((await cookies()).get(UI_COOKIE)?.value);

  return (
    <html lang="en" {...htmlThemeAttributes(preferences)}>
      <body className="bg-canvas font-sans text-ink">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
