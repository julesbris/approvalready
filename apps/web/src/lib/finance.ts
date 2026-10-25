/**
 * Mortgages and finance enquiries. ApprovalReady doesn't lend or give credit advice: every
 * finance call to action sends the enquiry to our finance team's contact form.
 */
import type { Vertical } from "@approvalready/shared-types";

/** Where every finance enquiry goes. */
export const FINANCE_ENQUIRY_URL = "https://approvalreadyai.com/#contact";

export interface FinanceOffer {
  heading: string;
  text: string;
}

/** The headline offer, used where the project area isn't known. */
export const FINANCE_OFFER: FinanceOffer = {
  heading: "Need a mortgage or finance?",
  text: "Home loans, refinancing, construction and development finance, business loans and asset finance for vehicles, vessels and equipment. Send an enquiry and a finance specialist will contact you.",
};

/** What finance fits each project area. */
const OFFERS: Record<Vertical, FinanceOffer> = {
  PLANNING: {
    heading: "Need finance to build or develop?",
    text: "Construction loans for a new home, granny flat or renovation, and development finance for subdivisions and multi-unit projects. Send an enquiry and a finance specialist will contact you.",
  },
  VESSEL: {
    heading: "Need finance for a vessel?",
    text: "Asset finance for commercial and recreational boats, plus engines, fit-outs and marine equipment. Send an enquiry and a finance specialist will contact you.",
  },
  BUSINESS: {
    heading: "Need finance for your business?",
    text: "Business loans, fit-out and equipment finance, and asset finance for vehicles and machinery. Send an enquiry and a finance specialist will contact you.",
  },
  GRANT: {
    heading: "Need finance alongside a grant?",
    text: "Most grants pay part of the cost or pay in arrears. Business loans and equipment or asset finance can cover the rest. Send an enquiry and a finance specialist will contact you.",
  },
  SELL: {
    heading: "Buying your next place?",
    text: "Home loans, bridging finance while you sell, and refinancing. Send an enquiry and a finance specialist will contact you.",
  },
  RENT: {
    heading: "Need an investment loan?",
    text: "Investment property loans, refinancing and equity release for your next purchase. Send an enquiry and a finance specialist will contact you.",
  },
  TRADE: {
    heading: "Need finance for importing or exporting?",
    text: "Asset finance for imported vehicles, machinery and equipment, and trade finance to pay suppliers before goods are sold. Send an enquiry and a finance specialist will contact you.",
  },
};

/** The offer for a project area, or the headline offer when the area is unknown. */
export function financeOffer(vertical?: string | null): FinanceOffer {
  return (vertical && OFFERS[vertical as Vertical]) || FINANCE_OFFER;
}

export interface FinanceService {
  title: string;
  text: string;
  points: string[];
}

/** The finance the /finance page lists. */
export const FINANCE_SERVICES: FinanceService[] = [
  {
    title: "Home loans and mortgages",
    text: "For buying a home, your next home, or switching to a better rate.",
    points: [
      "First home buyer loans",
      "Upgrading or downsizing",
      "Refinancing and debt consolidation",
      "Bridging finance while you sell",
    ],
  },
  {
    title: "Investment property loans",
    text: "For buying, holding and growing a rental portfolio.",
    points: ["Investment loans", "Equity release", "Self-managed super fund (SMSF) loans"],
  },
  {
    title: "Construction and development finance",
    text: "For building, renovating and developing once you know what council will approve.",
    points: [
      "Construction loans for a new home or granny flat",
      "Renovation and extension loans",
      "Land and subdivision finance",
      "Development finance for duplexes and multi-unit projects",
    ],
  },
  {
    title: "Asset finance",
    text: "For the vehicles, vessels and equipment your business or project needs.",
    points: [
      "Cars, utes, trucks and imported vehicles",
      "Commercial and recreational vessels",
      "Machinery, plant and equipment",
      "Fit-outs, technology and medical equipment",
    ],
  },
  {
    title: "Business and commercial finance",
    text: "For starting, buying or growing a business.",
    points: [
      "Business loans and lines of credit",
      "Buying a business or franchise",
      "Commercial property loans",
      "Trade finance for importers and exporters",
    ],
  },
];
