import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        primary: {
          50: "#E8F0FE",
          100: "#D2E3FC",
          200: "#AECBFA",
          300: "#8AB4F8",
          400: "#669DF6",
          500: "#4285F4",
          600: "#1A73E8",
          700: "#1967D2",
          800: "#185ABC",
          900: "#174EA6",
        },
        gray: {
          50: "#F8F9FA",
          100: "#F1F3F4",
          200: "#E8EAED",
          300: "#DADCE0",
          400: "#BDC1C6",
          500: "#9AA0A6",
          600: "#80868B",
          700: "#5F6368",
          800: "#3C4043",
          900: "#202124",
        },
        success: "#34A853",
        warning: "#FBBC04",
        danger: "#EA4335",
        background: "var(--bg-primary)",
        foreground: "var(--text-primary)",
      },
      fontFamily: {
        sans: ['"Google Sans"', '"Inter"', "system-ui", "sans-serif"],
        mono: ['"Google Sans Mono"', '"Geist Mono"', "monospace"],
      },
      borderRadius: {
        DEFAULT: "8px",
      },
      keyframes: {
        "fade-in-down": {
          "0%": { opacity: "0", transform: "translateX(-50%) translateY(-6px)" },
          "100%": { opacity: "1", transform: "translateX(-50%) translateY(0)" },
        },
      },
      animation: {
        "fade-in-down": "fade-in-down 0.15s ease-out",
      },
      boxShadow: {
        card: "0 1px 2px 0 rgba(60,64,67,0.3), 0 1px 3px 1px rgba(60,64,67,0.15)",
        "card-hover":
          "0 1px 3px 0 rgba(60,64,67,0.3), 0 4px 8px 3px rgba(60,64,67,0.15)",
        elevated:
          "0 4px 8px 3px rgba(60,64,67,0.15), 0 1px 3px rgba(60,64,67,0.3)",
      },
    },
  },
  plugins: [require("@tailwindcss/typography")],
};
export default config;
