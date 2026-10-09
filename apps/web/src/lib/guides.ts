/**
 * Public guide pages (statically generated for search). Every statement in a guide comes from
 * a listed source, and every guide says how far its sources have been checked. The same
 * sources back the Cairns rules in the API's content pack
 * (apps/api/app/modules/rules/packs/planning_qld_cairns.json); keep the two in step.
 */

export interface GuideSource {
  title: string;
  publisher: string;
  url: string;
  version: string;
}

export interface GuideSection {
  heading: string;
  paragraphs: string[];
  points?: string[];
}

export interface Guide {
  slug: string;
  title: string;
  description: string;
  area: string;
  /** When the sources were last read for this guide (ISO date). */
  checkedOn: string;
  /** How far a person has verified the sources against their current versions. */
  verification: "UNVERIFIED" | "VERIFIED";
  sections: GuideSection[];
  notCovered: string[];
  sources: GuideSource[];
}

const COUNCIL = "Cairns Regional Council";

const DWELLINGS_FACT_SHEET: GuideSource = {
  title: "CairnsPlan 2016 Fact Sheet: Dwelling houses, Secondary dwellings and Dual occupancy",
  publisher: COUNCIL,
  url: "https://www.cairns.qld.gov.au/__data/assets/pdf_file/0005/489641/CairnsPlan-2016-Fact-Sheet-Dwelling-houses-Secondary-dwellings-and-Dual-Occupancy.pdf",
  version: "#5030963 v8, last updated 25 October 2021",
};

const RAL_FACT_SHEET: GuideSource = {
  title: "CairnsPlan 2016 Fact Sheet: Reconfiguring a Lot",
  publisher: COUNCIL,
  url: "https://www.cairns.qld.gov.au/__data/assets/pdf_file/0008/489644/CairnsPlan-2016-Fact-Sheet-Reconfiguring-a-Lot.pdf",
  version: "#5031037 v3, last updated 22 October 2021",
};

const HILLSLOPES_FACT_SHEET: GuideSource = {
  title: "CairnsPlan 2016 Fact Sheet: Dwelling houses in the Hillslopes overlay",
  publisher: COUNCIL,
  url: "https://www.cairns.qld.gov.au/__data/assets/pdf_file/0010/489646/CairnsPlan-2016-Fact-sheet-Dwelling-houses-in-the-Hillslopes-Overlay.pdf",
  version: "#5031083 v8, last updated 22 October 2021",
};

const PLANNING_REGULATION: GuideSource = {
  title: "Planning Regulation 2017 (Qld), schedule 24 (dictionary)",
  publisher: "Queensland Legislation",
  url: "https://www.legislation.qld.gov.au/view/html/inforce/current/sl-2017-0078",
  version: "As amended by the Planning (Secondary Dwellings) Amendment Regulation 2022",
};

const STATE_SECONDARY_PAGE: GuideSource = {
  title: "Changes to secondary dwellings",
  publisher: "Queensland Government (planning.qld.gov.au)",
  url: "https://planning.qld.gov.au/planning-issues-and-interests/changes-to-secondary-dwellings",
  version: "Change took effect 26 September 2022",
};

export const GUIDES: Guide[] = [
  {
    slug: "cairns-secondary-dwellings",
    title: "Secondary dwellings (granny flats) in Cairns",
    description:
      "When a granny flat in the Cairns Regional Council area needs planning or building approval, how big it can be, parking, and who can live in it, with the sources for each point.",
    area: "Cairns Regional Council, Queensland",
    checkedOn: "2026-10-09",
    verification: "UNVERIFIED",
    sections: [
      {
        heading: "What counts as a secondary dwelling",
        paragraphs: [
          "Queensland's Planning Regulation 2017 describes a secondary dwelling as a dwelling on a lot that is used in conjunction with, but subordinate to, another dwelling. Council's fact sheet adds that it is smaller than the main house. A second home that can be separately serviced or sub-metered is a dual occupancy instead, which has different rules.",
        ],
      },
      {
        heading: "Does it need planning approval?",
        paragraphs: [
          "Council's fact sheet says that adding a secondary dwelling to a lot that already has a house is a material change of use. Whether that needs a development application depends on the zone's table of assessment in Part 5 of CairnsPlan 2016.",
          "A dwelling house, which can include a secondary dwelling, is generally accepted development subject to requirements in residential zones. If the design doesn't meet those requirements, a development application is needed.",
        ],
      },
      {
        heading: "How big can it be?",
        paragraphs: ["Council's fact sheet gives these maximum sizes for a secondary dwelling:"],
        points: [
          "Low density, Low-medium density, Medium density, Rural residential and Tourist accommodation zones: 70 m² (Tourist accommodation precinct 1, the islands, is excluded).",
          "Rural zone: 250 m² on lots over 10 hectares, or 70 m² on smaller lots.",
          "All other zones, on lots over 450 m²: 70 m².",
        ],
      },
      {
        heading: "Car parking",
        paragraphs: [
          "Council's fact sheet says a house with a secondary dwelling needs 3 car parking spaces in total. A dual occupancy needs 4.",
        ],
      },
      {
        heading: "Who can live in it?",
        paragraphs: [
          "Since 26 September 2022 the Planning Regulation no longer requires a secondary dwelling to be occupied by the same household as the main house, so it can be rented to anyone. Council's 2021 fact sheet still describes the older rule. Existing approvals with occupancy conditions may need a change application, and the change doesn't remove the need for any approval.",
        ],
      },
      {
        heading: "Building approval",
        paragraphs: [
          "As well as any planning approval, council's fact sheet says you need a building works approval for any building works. A building certifier assesses and issues it.",
        ],
      },
      {
        heading: "Steep land",
        paragraphs: [
          "On sites in council's Hillslopes overlay, the fact sheet says development does not occur on land steeper than 1 in 6 (16.6%), and limits earthworks: no more than 50 m³ of cut or fill, and batters or retaining walls no higher than 1.8 m. Work that doesn't meet these needs a development application.",
        ],
      },
    ],
    notCovered: [
      "The full text of CairnsPlan 2016, which has been amended since these fact sheets were last updated.",
      "Setbacks, height, site cover and design requirements of the dwelling house code.",
      "Overlays other than steep land (for example flooding, bushfire or heritage).",
      "Application fees and infrastructure charges.",
    ],
    sources: [DWELLINGS_FACT_SHEET, HILLSLOPES_FACT_SHEET, PLANNING_REGULATION, STATE_SECONDARY_PAGE],
  },
  {
    slug: "cairns-subdivision",
    title: "Subdividing land in Cairns",
    description:
      "What reconfiguring a lot means in the Cairns Regional Council area, when a development permit is needed, minimum lot sizes in the residential zones, and the costs to expect, with sources.",
    area: "Cairns Regional Council, Queensland",
    checkedOn: "2026-10-09",
    verification: "UNVERIFIED",
    sections: [
      {
        heading: "What reconfiguring a lot means",
        paragraphs: [
          "Subdividing is one kind of reconfiguring a lot. Council's fact sheet lists these under the Planning Act 2016:",
        ],
        points: [
          "creating lots by subdividing another lot;",
          "amalgamating two or more lots;",
          "rearranging lot boundaries by registering a plan of subdivision;",
          "dividing land into parts by agreement (with some exclusions for leases and community title);",
          "creating an easement that gives a lot access to a constructed road.",
        ],
      },
      {
        heading: "Do you need a development permit?",
        paragraphs: [
          "Council's fact sheet says reconfiguring a lot needs an application for a development permit where Part 5 of CairnsPlan 2016 makes it code or impact assessable. Check the level of assessment for your zone with council.",
        ],
      },
      {
        heading: "Minimum lot sizes",
        paragraphs: ["The fact sheet gives minimums for two residential zones:"],
        points: [
          "Low density residential: 600 m², with a minimum width and dimension of 15 m.",
          "Low-medium density residential: 450 m², or 350 m² where the small lot provisions are met.",
        ],
      },
      {
        heading: "Conditions, fees and charges",
        paragraphs: [
          "An approval may come with conditions about access, building envelopes, geotechnical matters, service connections, infrastructure works, staging and further studies. Application fees are in council's fees and charges schedule, and infrastructure charges apply to reconfiguring a lot.",
          "You may also need other approvals, such as a material change of use, building works or operational works, and connections to council's water and sewer.",
        ],
      },
    ],
    notCovered: [
      "Minimum lot sizes for zones other than the two above (Part 9 of CairnsPlan 2016 has them all).",
      "State referrals, overlays and the survey plan process.",
      "The full text of CairnsPlan 2016, which has been amended since the fact sheet was last updated.",
    ],
    sources: [RAL_FACT_SHEET],
  },
];

export function guide(slug: string): Guide | undefined {
  return GUIDES.find((g) => g.slug === slug);
}
