import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // Mirrors the dark Railway dashboard the project is most often viewed
        // alongside, so the operator can switch tabs without retina shock.
        bg: {
          DEFAULT: "#0b0d12",
          panel: "#13161d",
          hover: "#1c2029",
        },
        border: {
          DEFAULT: "#262b36",
          strong: "#3a4150",
        },
        accent: {
          green: "#26a69a",
          red: "#ef5350",
          blue: "#5b8def",
        },
      },
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;
