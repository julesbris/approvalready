import Link from "next/link";

import { SiteFooter } from "@/components/public/SiteFooter";
import { defaultBrand } from "@/lib/brand";

export default function HomePage() {
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
      <main className="container">
        <section className="hero" aria-labelledby="hero-title">
          <h1 id="hero-title">{brand.tagline}</h1>
          <p>{brand.description}</p>
          <p className="principle">
            Every result is based on published regulatory sources and shows how confident we are:
            verified, likely, review required, or unknown. We never guess at approvals, fees or
            dates.
          </p>
        </section>
        <ul className="products" aria-label="Product areas">
          {brand.products.map((product) => (
            <li key={product.key} className="product">
              <h2>{product.name}</h2>
              <p>{product.question}</p>
            </li>
          ))}
        </ul>
      </main>
      <SiteFooter />
    </>
  );
}
