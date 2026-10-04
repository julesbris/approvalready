import type { Metadata } from "next";
import type { ReactNode } from "react";

import "@approvalready/ui/tokens.css";
import "./globals.css";

import { defaultBrand } from "@/lib/brand";

export const metadata: Metadata = {
  title: { default: defaultBrand.productName, template: `%s | ${defaultBrand.productName}` },
  description: defaultBrand.description,
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en-AU">
      <body>{children}</body>
    </html>
  );
}
