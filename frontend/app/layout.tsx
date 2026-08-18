import type { Metadata } from "next";
import "./globals.css";
import { CreditFooter } from "@/components/CreditFooter";

export const metadata: Metadata = {
  title: "HORIZON GRID",
  description: "Unified threat intelligence workbench for SOC analysts and threat hunters.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen antialiased">
        <CreditFooter />
        {children}
      </body>
    </html>
  );
}
