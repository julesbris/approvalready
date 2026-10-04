/**
 * Design tokens. Restrained and trustworthy: neutral surfaces, one accent per brand,
 * no gradients, minimal motion. Brand accents are overridden at runtime from brand config.
 */
export const tokens = {
  color: {
    ink: "#14181f",
    inkMuted: "#4a5361",
    surface: "#ffffff",
    surfaceSubtle: "#f5f6f8",
    border: "#dde1e7",
    accent: "#1f4e79",
    accentInk: "#ffffff",
    success: "#1e6b3a",
    warning: "#8a5a00",
    danger: "#a1262b",
  },
  radius: { sm: "4px", md: "6px", lg: "10px" },
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
