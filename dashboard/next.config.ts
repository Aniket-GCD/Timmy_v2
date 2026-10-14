import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async redirects() {
    return [
      { source: "/time-by-job", destination: "/billing-dashboard", permanent: false },
    ];
  },
};

export default nextConfig;
