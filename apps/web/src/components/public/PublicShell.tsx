import type { ReactNode } from "react";

import { SiteFooter } from "@/components/public/SiteFooter";
import { SiteHeader } from "@/components/public/SiteHeader";

/** Header and footer for public, statically generated pages. */
export function PublicShell({ children }: { children: ReactNode }) {
  return (
    <>
      <SiteHeader />
      <main className="container">{children}</main>
      <SiteFooter />
    </>
  );
}
