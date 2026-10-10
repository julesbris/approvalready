import Link from "next/link";

import { defaultBrand } from "@/lib/brand";

/** Footer on every page: the advice disclaimer and the legal links. */
export function SiteFooter() {
  return (
    <footer className="site-footer">
      <div className="container">
        <p>
          {defaultBrand.productName} provides information and preparation tools. It is not
          legal, financial or planning advice.
        </p>
        <nav aria-label="Legal" className="footer-nav">
          <Link href="/terms">Terms of Use</Link>
          <Link href="/privacy">Privacy Policy</Link>
          <Link href="/contact">Contact</Link>
        </nav>
      </div>
    </footer>
  );
}
