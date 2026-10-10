import type { Metadata } from "next";
import localFont from "next/font/local";
import type { ReactNode } from "react";

import "@approvalready/ui/tokens.css";
import "./globals.css";

import { defaultBrand } from "@/lib/brand";

// The brand faces from the ApprovalReady.au design system (SIL Open Font License,
// src/fonts/OFL.txt), served from our own origin so the Content Security Policy can keep
// font-src 'self'. Outfit is the wordmark face, for headlines; Figtree for everything people
// read or type; JetBrains Mono for references people copy.
const outfit = localFont({
  src: [
    { path: "../fonts/Outfit-500.woff2", weight: "500" },
    { path: "../fonts/Outfit-600.woff2", weight: "600" },
    { path: "../fonts/Outfit-700.woff2", weight: "700" },
  ],
  display: "swap",
  variable: "--ar-font-outfit",
});

const figtree = localFont({
  src: [
    { path: "../fonts/Figtree-400.woff2", weight: "400" },
    { path: "../fonts/Figtree-500.woff2", weight: "500" },
    { path: "../fonts/Figtree-600.woff2", weight: "600" },
    { path: "../fonts/Figtree-700.woff2", weight: "700" },
  ],
  display: "swap",
  variable: "--ar-font-figtree",
});

const jetbrainsMono = localFont({
  src: [
    { path: "../fonts/JetBrainsMono-400.woff2", weight: "400" },
    { path: "../fonts/JetBrainsMono-500.woff2", weight: "500" },
  ],
  display: "swap",
  preload: false,
  variable: "--ar-font-jetbrains",
});

export const metadata: Metadata = {
  title: { default: defaultBrand.productName, template: `%s | ${defaultBrand.productName}` },
  description: defaultBrand.description,
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html
      lang="en-AU"
      className={`${outfit.variable} ${figtree.variable} ${jetbrainsMono.variable}`}
    >
      <body>{children}</body>
    </html>
  );
}
