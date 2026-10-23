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

const nextConfig: NextConfig = {
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
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

export default nextConfig;
