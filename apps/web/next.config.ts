import type { NextConfig } from "next";

import { staticCsp } from "./src/lib/csp";

const isProd = process.env.NODE_ENV === "production";

// Static pages get the baseline policy; dynamically rendered app/auth pages get a strict
// per-request nonce policy from src/proxy.ts instead (see src/lib/csp.ts).
const csp = staticCsp(!isProd);

const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=()" },
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
];

const config: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  reactStrictMode: true,
  transpilePackages: ["@approvalready/ui", "@approvalready/shared-types"],
  async headers() {
    return [
      { source: "/:path*", headers: securityHeaders },
      {
        // Everything except the nonce-CSP paths (NONCE_CSP_PATHS in src/lib/csp.ts).
        source:
          "/((?!login|register|verify-email|forgot-password|reset-password|account|invitations|projects|admin|review|notifications|partner).*)",
        headers: [{ key: "Content-Security-Policy", value: csp }],
      },
    ];
  },
};

export default config;
