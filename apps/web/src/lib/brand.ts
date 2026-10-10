/**
 * Brand resolution. Milestone 1 ships the default brand only; from Milestone 2-3 brands and
 * hostname mappings come from the `brand` / `brand_domain` tables via the API, with this
 * object kept as the build-time fallback for static generation. Never hard-code marketing
 * domains here beyond configuration.
 */
import type { Vertical } from "@approvalready/shared-types";

export interface ProductArea {
  key: Vertical;
  name: string;
  path: string;
  question: string;
}

export interface Brand {
  key: string;
  productName: string;
  tagline: string;
  description: string;
  products: ProductArea[];
}

export const defaultBrand: Brand = {
  key: "approvalready",
  productName: "ApprovalReady",
  tagline: "Know which approvals apply, and see the sources behind every answer.",
  description:
    "ApprovalReady helps Australian property owners, businesses, importers, exporters and vessel operators work out which approvals, licences and grants apply to them, prepare the evidence, and get professional help when they need it.",
  products: [
    {
      key: "PLANNING",
      name: "PlanningReady",
      path: "/planning",
      question: "What can I do with this property, and what approvals do I need?",
    },
    {
      key: "VESSEL",
      name: "VesselReady",
      path: "/vessel",
      question: "What do I need to operate this vessel commercially?",
    },
    {
      key: "BUSINESS",
      name: "BusinessReady",
      path: "/business",
      question: "What approvals do I need to start this business?",
    },
    {
      key: "GRANT",
      name: "GrantReady",
      path: "/grants",
      question: "Which grants might my organisation be eligible for?",
    },
    {
      key: "SELL",
      name: "SellReady",
      path: "/property/sell",
      question: "How do I prepare and manage a private property sale?",
    },
    {
      key: "RENT",
      name: "RentReady",
      path: "/property/rent",
      question: "How do I prepare and self-manage a residential rental?",
    },
    {
      key: "TRADE",
      name: "TradeReady",
      path: "/trade",
      question: "What do I need to import or export these goods?",
    },
  ],
};

/** Resolve the brand for a request hostname. Only the default brand exists in Milestone 1. */
export function resolveBrand(host: string | null | undefined): Brand {
  void host;
  return defaultBrand;
}
