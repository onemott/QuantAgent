import type { NextConfig } from "next";

const apiUrlFromEnv = process.env.NEXT_PUBLIC_API_URL || "";
const isDocker = apiUrlFromEnv.includes("backend:");
let backendUrl = isDocker ? "http://backend:8000" : "http://localhost:8002";
if (apiUrlFromEnv) {
  backendUrl = isDocker 
    ? apiUrlFromEnv.replace(":8002", ":8000") 
    : apiUrlFromEnv;
}

const nextConfig: NextConfig = {
  transpilePackages: ["date-fns"],
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: `${backendUrl}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
