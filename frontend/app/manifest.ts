import type { MetadataRoute } from "next";

// Lets a phone "Add to Home Screen" and open the dashboard as a standalone
// app. There is no native build; this site is the mobile version.
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "quant.futures",
    short_name: "quant",
    description: "CME futures analytics — charting, backtesting, pairs research.",
    start_url: "/",
    display: "standalone",
    background_color: "#0b0d12",
    theme_color: "#0b0d12",
    icons: [
      { src: "/icon.png", sizes: "any", type: "image/png" },
      { src: "/apple-icon.png", sizes: "180x180", type: "image/png" },
    ],
  };
}
