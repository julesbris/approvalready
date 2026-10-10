import Link from "next/link";

import { defaultBrand } from "@/lib/brand";

/**
 * The logo: a tick in a rounded square, then the product name (and an optional suffix such as
 * "Partners"). Links home by default.
 */
export function Wordmark({ href = "/", suffix }: { href?: string; suffix?: string }) {
  return (
    <Link className="wordmark" href={href}>
      <svg className="wordmark-mark" viewBox="0 0 32 32" aria-hidden="true" focusable="false">
        <rect width="32" height="32" rx="9" />
        <path d="M9.5 16.5l4.5 4.5 8.5-9.5" />
      </svg>
      <span>
        {defaultBrand.productName}
        {suffix ? <span className="wordmark-suffix"> {suffix}</span> : null}
      </span>
    </Link>
  );
}
