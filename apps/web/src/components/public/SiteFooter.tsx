import Link from "next/link";

import { Wordmark } from "@/components/brand/Wordmark";
import { defaultBrand } from "@/lib/brand";

/** Footer on every page: the product areas, the advice disclaimer and the legal links. */
export function SiteFooter() {
  return (
    <footer className="site-footer">
      <div className="container">
        <div className="footer-grid">
          <div className="footer-brand">
            <Wordmark tone="reversed" />
            <p>
              {defaultBrand.productName} provides information and preparation tools. It is not
              legal, financial or planning advice.
            </p>
          </div>
          <div>
            <p className="footer-heading">Products</p>
            <ul className="footer-list">
              {defaultBrand.products.map((product) => (
                <li key={product.key}>{product.name}</li>
              ))}
            </ul>
          </div>
          <nav aria-label="Legal">
            <p className="footer-heading">Company</p>
            <ul className="footer-list footer-nav">
              <li>
                <Link href="/guides">Guides</Link>
              </li>
              <li>
                <Link href="/terms">Terms of Use</Link>
              </li>
              <li>
                <Link href="/privacy">Privacy Policy</Link>
              </li>
              <li>
                <Link href="/contact">Contact</Link>
              </li>
            </ul>
          </nav>
        </div>
      </div>
    </footer>
  );
}
