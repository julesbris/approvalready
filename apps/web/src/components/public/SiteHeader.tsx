import Link from "next/link";

import { Wordmark } from "@/components/brand/Wordmark";
import { MenuDisclosure } from "@/components/public/MenuDisclosure";

/**
 * Header for public pages: the logo, the guides, sign in and a call to get started. Small
 * screens keep the call to get started and move the other links into a menu.
 */
export function SiteHeader() {
  return (
    <header className="site-header">
      <div className="container">
        <Wordmark />
        <div className="public-actions">
          <nav className="public-nav" aria-label="Site">
            <Link href="/guides">Guides</Link>
            <Link href="/login">Sign in</Link>
          </nav>
          <Link className="button button-small" href="/register">
            Get started
          </Link>
          <MenuDisclosure>
            <Link href="/guides">Guides</Link>
            <Link href="/login">Sign in</Link>
            <Link href="/register">Create an account</Link>
          </MenuDisclosure>
        </div>
      </div>
    </header>
  );
}
