/**
 * Public guide pages (statically generated for search). Every statement in a guide comes from
 * a listed source, and every guide says how far its sources have been checked. The same
 * sources back the rules in the API's content packs
 * (apps/api/app/modules/rules/packs/planning_qld_cairns.json and trade_au.json); keep them in
 * step.
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

const ABF_IMPORT_DECLARATIONS: GuideSource = {
  title: "Import declarations (fact sheet)",
  publisher: "Australian Border Force",
  url: "https://www.abf.gov.au/help-and-support-subsite/FactSheets/import-declarations.pdf",
  version: "Read 10 October 2026",
};

const ABF_PROHIBITED: GuideSource = {
  title: "Prohibited goods",
  publisher: "Australian Border Force",
  url: "https://www.abf.gov.au/importing-exporting-and-manufacturing/prohibited-goods",
  version: "Read 10 October 2026",
};

const BGA_IMPORTING: GuideSource = {
  title: "Importing and your business",
  publisher: "business.gov.au",
  url: "https://business.gov.au/products-and-services/importing/importing-and-your-business",
  version: "Read 10 October 2026",
};

const BGA_EXPORTING: GuideSource = {
  title: "Exporting and your business",
  publisher: "business.gov.au",
  url: "https://business.gov.au/products-and-services/exporting/exporting-and-your-business",
  version: "Read 10 October 2026",
};

const BICON: GuideSource = {
  title: "Biosecurity Import Conditions system (BICON)",
  publisher: "Department of Agriculture, Fisheries and Forestry",
  url: "https://www.agriculture.gov.au/biosecurity-trade/import/online-services/bicon",
  version: "Read 10 October 2026",
};

const BMSB_GOODS: GuideSource = {
  title: "Target high risk and risk goods for the Brown Marmorated Stink Bug (fact sheet)",
  publisher: "Department of Agriculture, Fisheries and Forestry",
  url: "https://www.agriculture.gov.au/sites/default/files/documents/factsheet3-goods-subject-to-bmsb-measures.pdf",
  version: "Read 10 October 2026",
};

const DAFF_EXPORTING: GuideSource = {
  title: "Exporting from Australia",
  publisher: "Department of Agriculture, Fisheries and Forestry",
  url: "https://www.agriculture.gov.au/biosecurity-trade/export/from-australia",
  version: "Read 10 October 2026",
};

const DEFENCE_PERMITS: GuideSource = {
  title: "Permits (Defence export controls)",
  publisher: "Department of Defence",
  url: "https://www.defence.gov.au/business-industry/exporting/applications-and-pre-notification/permits",
  version: "Read 10 October 2026",
};

const ATO_DEFERRED_GST: GuideSource = {
  title: "What is the deferred GST scheme?",
  publisher: "Australian Taxation Office",
  url: "https://www.ato.gov.au/businesses-and-organisations/gst-excise-and-indirect-taxes/gst/in-detail/rules-for-specific-transactions/international-transactions/deferred-gst",
  version: "Read 10 October 2026",
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
  {
    slug: "importing-goods-into-australia",
    title: "Importing goods into Australia for your business",
    description:
      "When you need a full import declaration, who can lodge it, GST and duty, biosecurity permits and stink bug season, and goods that need permission first, with the sources for each point.",
    area: "Australia",
    checkedOn: "2026-10-10",
    verification: "UNVERIFIED",
    sections: [
      {
        heading: "Do you need a full import declaration?",
        paragraphs: [
          "The Australian Border Force says goods valued above A$1,000 that arrive by mail, air cargo or sea cargo generally need an import declaration before they are cleared. business.gov.au says most goods worth A$1,000 or less can come in without one, but prohibited or restricted goods and biosecurity rules apply whatever the value.",
          "You can lodge the declaration yourself in the Integrated Cargo System, which needs client registration and a digital certificate, or a licensed customs broker can lodge it for you. Keep your import records for five years.",
        ],
      },
      {
        heading: "GST, duty and other charges",
        paragraphs: [
          "Most imports attract 10% GST. Depending on the goods you may also pay customs duty, import processing charges, dumping duties, and brokerage, permit and biosecurity fees. Check for concessions such as free trade agreement rates.",
          "The ATO's deferred GST scheme lets eligible importers pay import GST in their monthly business activity statement instead of at the border. You need an ABN, GST registration and monthly BAS lodged online.",
        ],
      },
      {
        heading: "Biosecurity",
        paragraphs: [
          "Food, plants, animal products and timber have biosecurity import conditions. The department's BICON system shows, for your exact goods, whether you need a permit, treatment or documents. Goods that need a permit but arrive without one are exported or destroyed, and permits usually take 20 to 40 business days.",
          "From 1 September to 30 April, goods such as timber, stone, ceramics, glass, metal, machinery, electrical equipment and vehicles shipped from listed countries in Europe, Central Asia and North America need treatment for brown marmorated stink bug. Break bulk, flat rack and open-top cargo must be treated before it leaves.",
        ],
      },
      {
        heading: "Goods that need permission first",
        paragraphs: [
          "Some goods are prohibited unless you have written permission, and importing them without it can mean seizure and heavy penalties. The Border Force names tobacco as one example. Other regulated goods include:",
        ],
        points: [
          "road vehicles, which need an import approval before they are shipped;",
          "industrial chemicals and products containing them, such as cosmetics, soap, paint or glue, which need AICIS registration;",
          "firearms and weapons, which a customs broker checks against government requirements before release;",
          "equipment with refrigerant gas, household electrical equipment, medicines and medical devices, and wildlife products, which have their own licences and registrations.",
        ],
      },
    ],
    notCovered: [
      "The Customs Act 1901 and the Customs (Prohibited Imports) Regulations themselves.",
      "Tariff classification, duty rates and free trade agreement rules of origin.",
      "Product safety bans, mandatory standards and labelling rules.",
      "Vaping products, which have their own controls.",
    ],
    sources: [
      ABF_IMPORT_DECLARATIONS,
      BGA_IMPORTING,
      ABF_PROHIBITED,
      BICON,
      BMSB_GOODS,
      ATO_DEFERRED_GST,
    ],
  },
  {
    slug: "exporting-goods-from-australia",
    title: "Exporting goods from Australia",
    description:
      "When you need an export declaration, export controls on food, plant and animal goods, Defence export permits and export grants, with the sources for each point.",
    area: "Australia",
    checkedOn: "2026-10-10",
    verification: "UNVERIFIED",
    sections: [
      {
        heading: "Do you need an export declaration?",
        paragraphs: [
          "business.gov.au says goods worth more than A$2,000 generally need an export declaration before they can leave Australia, and some goods can't be exported without a permit whatever their value. A customs broker or freight forwarder usually lodges the declaration.",
        ],
      },
      {
        heading: "Food, plant and animal goods",
        paragraphs: [
          "The Department of Agriculture, Fisheries and Forestry controls exports of prescribed goods: dairy, eggs, fish, live animals, meat, poultry, wild game, organic products, plants and wood. Premises that prepare or store them for export must be registered establishments under the Export Control Act 2020, and shipments need government export documents. The importing country's own requirements are in the Manual of Importing Country Requirements (MICoR).",
        ],
      },
      {
        heading: "Military and dual-use goods",
        paragraphs: [
          "Goods, software and technology on the Defence and Strategic Goods List, including dual-use items, need a permit from Defence Export Controls before export. Firearms, parts and ammunition always need one. Applications go through the MADE portal.",
        ],
      },
      {
        heading: "Help with costs",
        paragraphs: [
          "Austrade's Export Market Development Grants help Australian businesses grow their exports.",
        ],
      },
    ],
    notCovered: [
      "The Customs (Prohibited Exports) Regulations and trade sanctions.",
      "Cultural heritage objects and wildlife permits in detail.",
      "The importing country's tariffs, labelling and certification rules.",
    ],
    sources: [BGA_EXPORTING, DAFF_EXPORTING, DEFENCE_PERMITS],
  },
];

export function guide(slug: string): Guide | undefined {
  return GUIDES.find((g) => g.slug === slug);
}
