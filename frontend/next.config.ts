import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  // Next's own dev-mode indicator badge (bottom-left "N" circle) — a
  // dev-only build/devtools affordance with no function in this app, and it
  // visually overlaps the sidebar's real NodeStatus connection card. Never
  // appears in a production build regardless; disabled here so it doesn't
  // during local dev either.
  devIndicators: false,
};

export default nextConfig;
