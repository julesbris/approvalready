import Link from "next/link";

import { Wordmark } from "@/components/brand/Wordmark";

/** Header for public pages: the logo, the guides, sign in and a call to get started. */
export function SiteHeader() {
  return (
    <header className="site-header">
      <div className="container">
        <Wordmark />
        <nav className="public-nav" aria-label="Site">
          <Link href="/guides">Guides</Link>
          <Link href="/login">Sign in</Link>
          <Link className="button button-small" href="/register">
            Get started
          </Link>
        </nav>
      </div>
    </header>
  );
}
