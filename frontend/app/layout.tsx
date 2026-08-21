import type { Metadata } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans_Condensed, Inter } from "next/font/google";
import "./globals.css";
import { CreditFooter } from "@/components/CreditFooter";

// Three faces, three jobs -- only the display face is new to the page.
// Body text (Inter) is unchanged from whatever it rendered as before, so the
// highest-risk, lowest-payoff move (re-tuning every table/row-height to a
// new body face's metrics) is avoided entirely; the identity shift lives
// in the display face (wordmark, section labels) and the data face
// (hashes, IPs, timestamps, counts -- anything that's a reading, not prose).
const bodyFont = Inter({ subsets: ["latin"], variable: "--font-body" });
const displayFont = IBM_Plex_Sans_Condensed({
  subsets: ["latin"],
  weight: ["500", "600", "700"],
  variable: "--font-display",
});
const dataFont = IBM_Plex_Mono({ subsets: ["latin"], weight: ["400", "500"], variable: "--font-data" });

export const metadata: Metadata = {
  title: "HORIZON GRID",
  description: "Every Signal. One Operational Picture. Unified threat intelligence workbench for SOC analysts and threat hunters.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`dark ${bodyFont.variable} ${displayFont.variable} ${dataFont.variable}`}>
      <body className="min-h-screen antialiased">
        <CreditFooter />
        {children}
      </body>
    </html>
  );
}
