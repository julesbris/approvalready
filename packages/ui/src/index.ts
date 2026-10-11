/**
 * Design tokens from the ApprovalReady.au design system, mirrored in tokens.css. Navy and white
 * lead; teal is the reward, kept for what is done, ready or approved. Status always carries a
 * word as well as a colour.
 */
export const tokens = {
  color: {
    brandNavy: "#012455",
    brandBlue: "#01387f",
    brandTeal: "#00cab5",
    brandTealDeep: "#00776b",
    brandMist: "#e6faf7",
    ink: "#0a1a33",
    inkMuted: "#4b5b74",
    surface: "#ffffff",
    surfaceSunk: "#f2f5f9",
    border: "#d7dfea",
    borderStrong: "#7f90a9",
    primary: "#012455",
    onPrimary: "#ffffff",
    accent: "#00cab5",
    onAccent: "#012455",
    success: "#00695f",
    warning: "#9a4a00",
    danger: "#b3261e",
    info: "#01387f",
  },
  radius: { sm: "6px", md: "10px", lg: "16px", xl: "24px", pill: "999px" },
  space: { xs: "4px", sm: "8px", md: "16px", lg: "24px", xl: "32px", xxl: "48px", xxxl: "64px" },
  font: {
    display: '"Outfit", "Figtree", system-ui, sans-serif',
    sans: '"Figtree", system-ui, -apple-system, "Segoe UI", sans-serif',
    mono: '"JetBrains Mono", ui-monospace, "SFMono-Regular", Menlo, monospace',
  },
} as const;

/** Visual treatment per confidence level, so findings read consistently everywhere. */
export const confidenceStyle = {
  VERIFIED: { label: "Verified", color: tokens.color.success },
  LIKELY: { label: "Likely", color: tokens.color.info },
  REVIEW_REQUIRED: { label: "Review required", color: tokens.color.warning },
  UNKNOWN: { label: "Unknown", color: tokens.color.inkMuted },
} as const;
