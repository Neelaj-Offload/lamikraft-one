// Devanagari faces are fetched only when Hindi text is rendered (unicode-range).
import "@fontsource/noto-sans-devanagari/400.css";
import "@fontsource/noto-sans-devanagari/600.css";
import "./globals.css";

import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";
import { cookies } from "next/headers";
import type { ReactNode } from "react";
import { htmlThemeAttributes, parseUiPreferences, UI_COOKIE } from "@/lib/ui-preferences";
import { Providers } from "./providers";

// The design system's own faces. next/font preloads them and sets size-adjusted fallbacks, so text
// does not shift when they arrive. tokens.css reads these variables into --font-sans/serif/mono.
const sans = localFont({
  src: [
    { path: "../fonts/InstrumentSans-Variable.woff2", weight: "400 700", style: "normal" },
    { path: "../fonts/InstrumentSans-Italic-Variable.woff2", weight: "400 700", style: "italic" },
  ],
  variable: "--lk-face-sans",
  display: "swap",
  fallback: ["Helvetica Neue", "Arial", "sans-serif"],
});
const serif = localFont({
  src: [
    { path: "../fonts/InstrumentSerif-Regular.woff2", weight: "400", style: "normal" },
    { path: "../fonts/InstrumentSerif-Italic.woff2", weight: "400", style: "italic" },
  ],
  variable: "--lk-face-serif",
  display: "swap",
  fallback: ["Times New Roman", "Georgia", "serif"],
});
const mono = localFont({
  src: [{ path: "../fonts/GeistMono-Variable.woff2", weight: "300 700", style: "normal" }],
  variable: "--lk-face-mono",
  display: "swap",
  preload: false,
  fallback: ["ui-monospace", "Menlo", "monospace"],
});

export const metadata: Metadata = {
  title: {
    default: "Lamikraft One",
    template: "%s · Lamikraft One",
  },
  description: "Lamikraft One: enquiries, quotations, stock and orders in one place.",
  applicationName: "Lamikraft One",
  icons: { icon: "/brand/lamikraft-favicon.png" },
  robots: { index: false, follow: false },
  formatDetection: { telephone: false, email: false, address: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  colorScheme: "light dark",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f2efe9" },
    { media: "(prefers-color-scheme: dark)", color: "#0c0a09" },
  ],
};

export default async function RootLayout({ children }: { children: ReactNode }) {
  const preferences = parseUiPreferences((await cookies()).get(UI_COOKIE)?.value);

  return (
    <html lang="en" className={`${sans.variable} ${serif.variable} ${mono.variable}`} {...htmlThemeAttributes(preferences)}>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
