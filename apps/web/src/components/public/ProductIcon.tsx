import type { Vertical } from "@approvalready/shared-types";

/** Simple line icons for the product areas, drawn on a 24px grid in currentColor. */
const PATHS: Partial<Record<Vertical, string[]>> = {
  PLANNING: ["M3 11.5 12 4l9 7.5", "M5.5 9.5V20h13V9.5", "M10 20v-5.5h4V20"],
  VESSEL: ["M12 3v11", "M12 4.5l6 8h-6", "M4 15h16l-2.5 4.5h-11Z"],
  BUSINESS: ["M4 8h16v11H4Z", "M9 8V5.5h6V8", "M4 13h16"],
  GRANT: ["M12 3.5 14.6 9l5.9.6-4.4 4 1.3 5.9L12 16.4l-5.4 3.1 1.3-5.9-4.4-4L9.4 9Z"],
  SELL: ["M3.5 12.5 11.5 4.5h8v8l-8 8Z", "M15.5 8.5h.01"],
  TRADE: ["M3 8l9-4 9 4v8l-9 4-9-4Z", "M3 8l9 4 9-4", "M12 12v8"],
  RENT: ["M18.5 9.5a4 4 0 1 1-8 0 4 4 0 0 1 8 0Z", "M11.6 12.3 4 20v.5h3v-2.5h2.5v-2.5l1.6-1.6"],
};

/** The icon for a product area (decorative: the product name always sits next to it). */
export function ProductIcon({ vertical }: { vertical: Vertical }) {
  const paths = PATHS[vertical] ?? PATHS.PLANNING ?? [];
  return (
    <span className="product-icon" aria-hidden="true">
      <svg viewBox="0 0 24 24" focusable="false">
        {paths.map((d) => (
          <path key={d} d={d} />
        ))}
      </svg>
    </span>
  );
}
