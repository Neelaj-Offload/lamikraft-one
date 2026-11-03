import path from "node:path";
import type { NextConfig } from "next";

// The npm workspace root: node_modules and package-lock.json live there.
const repoRoot = path.join(__dirname, "../..");

// Rewrites are resolved when the server starts in dev and baked in at `next build`
// for `next start`, so set LK_API_INTERNAL_URL before building for other targets.
const apiOrigin = (process.env.LK_API_INTERNAL_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "");

const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "X-Frame-Options", value: "DENY" },
  {
    key: "Permissions-Policy",
    value: "microphone=(self), camera=(self), geolocation=(), payment=(), usb=()",
  },
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
];

// Build workers: Next starts one per CPU, which can exhaust memory on a busy machine (each worker
// holds its own heap). LK_NEXT_BUILD_CPUS caps them; unset keeps Next's default.
const buildCpus = Number.parseInt(process.env.LK_NEXT_BUILD_CPUS ?? "", 10);

const nextConfig: NextConfig = {
  ...(Number.isFinite(buildCpus) && buildCpus > 0 ? { experimental: { cpus: buildCpus } } : {}),
  poweredByHeader: false,
  reactStrictMode: true,
  typedRoutes: true,
  outputFileTracingRoot: repoRoot,
  turbopack: {
    root: repoRoot,
  },
  async rewrites() {
    return {
      // beforeFiles: no Next route can shadow the FastAPI namespace.
      beforeFiles: [{ source: "/api/:path*", destination: `${apiOrigin}/api/:path*` }],
      afterFiles: [],
      fallback: [],
    };
  },
  async headers() {
    return [
      { source: "/:path*", headers: securityHeaders },
      // One-time demo links carry a token in the URL fragment (api-conventions §7): the page
      // strips it, and this policy keeps the URL out of any Referer. Listed last so it wins.
      {
        source: "/demo-sign-in",
        headers: [
          { key: "Referrer-Policy", value: "no-referrer" },
          { key: "Cache-Control", value: "no-store" },
        ],
      },
      // Invitation and password-reset links carry their token in the fragment too (platform-2).
      {
        source: "/(invite|reset-password)",
        headers: [
          { key: "Referrer-Policy", value: "no-referrer" },
          { key: "Cache-Control", value: "no-store" },
        ],
      },
    ];
  },
};

export default nextConfig;
