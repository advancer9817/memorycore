/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  async rewrites() {
    const apiUrl = process.env.MCORE_API_URL || "http://127.0.0.1:8318";
    return [
      { source: "/api/v1/:path*",         destination: `${apiUrl}/api/v1/:path*` },
      { source: "/api/curator/:path*",    destination: `${apiUrl}/api/curator/:path*` },
      { source: "/api/governance/:path*", destination: `${apiUrl}/api/governance/:path*` },
      { source: "/api/context",           destination: `${apiUrl}/api/context` },
    ];
  },
  eslint: {
    ignoreDuringBuilds: true,
  },
  typescript: {
    ignoreBuildErrors: true,
  },
  images: {
    unoptimized: true,
  },
}

export default nextConfig
