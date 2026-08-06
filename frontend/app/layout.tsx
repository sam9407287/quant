import type { Metadata } from "next";
import "./globals.css";
import { Nav } from "@/components/nav";
import { AuthProvider } from "@/lib/auth";

// Next derives the icon <link> tags from app/icon.png, app/favicon.ico and
// app/apple-icon.png, and the preview card from app/opengraph-image.png —
// none of those need declaring here. metadataBase is what turns the
// generated image path into the absolute URL a link unfurler needs.
export const metadata: Metadata = {
  metadataBase: new URL("https://quant.samlabhq.com"),
  title: {
    default: "quant.futures",
    template: "%s · quant.futures",
  },
  description: "CME index futures analytics — charting, backtesting and strategy research.",
  openGraph: {
    title: "quant.futures",
    description: "CME index futures analytics — charting, backtesting and strategy research.",
    url: "https://quant.samlabhq.com",
    siteName: "quant.futures",
    type: "website",
  },
  twitter: { card: "summary_large_image" },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-bg text-zinc-100">
        <AuthProvider>
          <Nav />
          <main className="mx-auto max-w-7xl px-6 py-8">{children}</main>
        </AuthProvider>
      </body>
    </html>
  );
}
