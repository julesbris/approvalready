/**
 * Design tokens, mirrored in tokens.css. Clean and trustworthy: near-black ink, soft grey
 * canvases, white rounded cards, pill buttons, one accent per brand, no gradients and minimal
 * motion. Brand accents are overridden at runtime from brand config.
 */
export const tokens = {
  color: {
    ink: "#0d1321",
    inkMuted: "#545e6f",
    surface: "#ffffff",
    surfaceSubtle: "#f3f5f9",
    border: "#e1e5ec",
    accent: "#2e46d1",
    accentSoft: "#ebeefd",
    accentInk: "#ffffff",
    success: "#11743f",
    warning: "#9a5800",
    danger: "#c0262d",
  },
  radius: { sm: "8px", md: "12px", lg: "20px", xl: "32px", pill: "999px" },
  space: { xs: "4px", sm: "8px", md: "16px", lg: "24px", xl: "40px", xxl: "64px" },
  font: {
    sans: 'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
  },
} as const;

/** Visual treatment per confidence level, so findings read consistently everywhere. */
export const confidenceStyle = {
  VERIFIED: { label: "Verified", color: tokens.color.success },
  LIKELY: { label: "Likely", color: tokens.color.accent },
  REVIEW_REQUIRED: { label: "Review required", color: tokens.color.warning },
  UNKNOWN: { label: "Unknown", color: tokens.color.inkMuted },
} as const;
