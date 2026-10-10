import Link from "next/link";
import type { ReactNode } from "react";

import { SiteFooter } from "@/components/public/SiteFooter";
import { defaultBrand } from "@/lib/brand";

/** Header and footer for public, statically generated pages. */
export function PublicShell({ children }: { children: ReactNode }) {
  const brand = defaultBrand;
  return (
    <>
      <header className="site-header">
        <div className="container">
          <Link className="wordmark" href="/">
            {brand.productName}
          </Link>
          <nav className="public-nav" aria-label="Site">
            <Link href="/guides">Guides</Link>
            <Link href="/login">Sign in</Link>
          </nav>
        </div>
      </header>
      <main className="container">{children}</main>
      <SiteFooter />
    </>
  );
}
