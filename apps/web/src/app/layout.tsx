import type { Metadata } from "next";
import localFont from "next/font/local";
import type { ReactNode } from "react";

import "@approvalready/ui/tokens.css";
import "./globals.css";

import { defaultBrand } from "@/lib/brand";

// Inter (SIL Open Font License, src/fonts/Inter-OFL.txt), served from our own origin so the
// Content Security Policy can keep font-src 'self'.
const inter = localFont({
  src: "../fonts/InterVariable-latin.woff2",
  weight: "100 900",
  display: "swap",
  variable: "--ar-font-inter",
});

export const metadata: Metadata = {
  title: { default: defaultBrand.productName, template: `%s | ${defaultBrand.productName}` },
  description: defaultBrand.description,
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en-AU" className={inter.variable}>
      <body>{children}</body>
    </html>
  );
}
