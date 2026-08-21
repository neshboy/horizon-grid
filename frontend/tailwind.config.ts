import type { Config } from "tailwindcss";

// Dark-mode-first SOC dashboard palette. Colors are HSL CSS variables (see
// app/globals.css) so components can be themed without editing this file.
const config: Config = {
  darkMode: "class",
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        card: "hsl(var(--card))",
        "card-foreground": "hsl(var(--card-foreground))",
        border: "hsl(var(--border))",
        muted: "hsl(var(--muted))",
        "muted-foreground": "hsl(var(--muted-foreground))",
        primary: "hsl(var(--primary))",
        "primary-foreground": "hsl(var(--primary-foreground))",
        destructive: "hsl(var(--destructive))",
        "destructive-foreground": "hsl(var(--destructive-foreground))",
        warning: "hsl(var(--warning))",
        success: "hsl(var(--success))",
        "success-foreground": "hsl(var(--success-foreground))",
        accent: "hsl(var(--accent))",
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
        // Radius-contrast rule: outer panels/cards keep the softer default
        // radius above; interactive/status elements (badges, buttons,
        // inputs, chips) use this tighter one instead -- soft panels
        // visibly containing sharp, precise controls reads as "tactical
        // instrument" rather than "generic SaaS," independent of color.
        tight: "var(--radius-tight)",
      },
      fontFamily: {
        // Body text stays whatever it already was; only referenced
        // explicitly where a component wants to force it over an inherited
        // display/data face (e.g. inside a .font-display container).
        sans: ["var(--font-body)", "ui-sans-serif", "system-ui", "sans-serif"],
        display: ["var(--font-display)", "ui-sans-serif", "system-ui", "sans-serif"],
        data: ["var(--font-data)", "ui-monospace", "SFMono-Regular", "monospace"],
      },
    },
  },
  plugins: [],
};
export default config;
