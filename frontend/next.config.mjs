/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Emit a self-contained server bundle so the production Docker image can
  // ship just `.next/standalone` and `.next/static` instead of dragging the
  // entire node_modules tree along — substantially smaller image, faster
  // cold start on Railway.
  output: "standalone",
};

export default nextConfig;
