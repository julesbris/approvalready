import Link from "next/link";

/** The horizontal lockup's proportions (public/brand/ar-lockup-horizontal.svg, 697 × 128). */
const LOCKUP_RATIO = 697 / 128;

/**
 * The ApprovalReady.au logo, as supplied in the design system (public/brand/): never redrawn
 * or set in live text. `tone="reversed"` is for navy grounds; the default follows the colour
 * scheme. An optional suffix such as "Partners" names the area. Links home by default.
 */
export function Wordmark({
  href = "/",
  suffix,
  tone = "auto",
  height = 36,
}: {
  href?: string;
  suffix?: string;
  tone?: "auto" | "reversed";
  height?: number;
}) {
  const width = Math.round(height * LOCKUP_RATIO);
  const reversed = "/brand/ar-lockup-horizontal-reversed.svg";
  return (
    <Link className="wordmark" href={href}>
      <picture>
        {tone === "auto" ? (
          <source srcSet={reversed} media="(prefers-color-scheme: dark)" />
        ) : null}
        <img
          className="wordmark-logo"
          src={tone === "reversed" ? reversed : "/brand/ar-lockup-horizontal.svg"}
          alt="ApprovalReady.au"
          width={width}
          height={height}
        />
      </picture>
      {suffix ? <span className="wordmark-suffix">{suffix}</span> : null}
    </Link>
  );
}
