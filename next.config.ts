import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  ...(process.env.AISITES_EXPORT === "1" ? { output: "export" as const } : {}),
};

export default nextConfig;
