/**
 * Public pages for the step-by-step approval guides, one per guide at
 * `/guides/<state>/<slug>`, with a hub page per state (`/guides/<state>`).
 *
 * The guides themselves live with the API (apps/api/app/modules/guidance): this reads the
 * same files at build time, so every page is statically generated and search engines see the
 * whole guide. `public_paths.json` (written by `python -m app.modules.guidance.pack`) says
 * where each guide's page is, so these pages and the marketing posts that link to them always
 * agree.
 */
import type { ApprovalGuideOut, OfficialForm } from "@approvalready/shared-types";

import guideFile from "../../../api/app/modules/guidance/approval_guides.json";
import formFile from "../../../api/app/modules/guidance/official_forms.json";
import pathFile from "../../../api/app/modules/guidance/public_paths.json";

export interface GuideState {
  code: string;
  segment: string;
  name: string;
}

export interface PublicGuide extends ApprovalGuideOut {
  state: GuideState;
  slug: string;
  path: string;
  /** The guide's ref in the marketing module (its image cards are named after it). */
  ref: string;
}

export interface Scenario {
  vertical: string;
  name: string;
  /** What someone in this scenario is trying to do, for headings and descriptions. */
  doing: string;
}

/** The scenarios a guide can be for, in the order hub pages show them. */
export const SCENARIOS: Scenario[] = [
  { vertical: "PLANNING", name: "Building and planning", doing: "build, renovate or subdivide" },
  { vertical: "BUSINESS", name: "Starting a business", doing: "start or run a business" },
  { vertical: "SELL", name: "Selling a home", doing: "sell a home" },
  { vertical: "RENT", name: "Renting out a home", doing: "rent out a home" },
  { vertical: "VESSEL", name: "Boats and jet skis", doing: "register and drive a boat" },
  { vertical: "TRADE", name: "Importing and exporting", doing: "import or export goods" },
];

export function scenario(vertical: string): Scenario | undefined {
  return SCENARIOS.find((s) => s.vertical === vertical);
}

type RawGuide = Omit<ApprovalGuideOut, "checked" | "forms" | "slug"> & {
  slug?: string | null;
  forms?: string[];
};

type RawForm = Partial<OfficialForm> & Pick<OfficialForm, "id" | "name" | "publisher" | "url">;

/** A form as the API serves it: optional fields filled in as their defaults. */
function form(raw: RawForm): OfficialForm {
  return {
    ...raw,
    code: raw.code ?? null,
    mentions: raw.mentions ?? [],
    verticals: raw.verticals ?? [],
    note: raw.note ?? null,
  };
}

const FORMS = new Map((formFile.forms as unknown as RawForm[]).map((f) => [f.id, form(f)]));
const STATES = pathFile.states as GuideState[];
const PATHS = new Map(pathFile.guides.map((p) => [p.kind, p]));

function normalise(raw: RawGuide): PublicGuide {
  const where = PATHS.get(raw.kind);
  const state = STATES.find((s) => s.segment === where?.state);
  if (!where || !state) {
    throw new Error(`${raw.kind} has no public page: run python -m app.modules.guidance.pack`);
  }
  const step = (s: ApprovalGuideOut["steps"][number]) => ({
    ...s,
    timeframe: s.timeframe ?? null,
    cost: s.cost ?? null,
    form: s.form ?? null,
    url: s.url ?? null,
  });
  return {
    ...raw,
    slug: where.slug,
    timeframe: raw.timeframe ?? null,
    cost_summary: raw.cost_summary ?? null,
    before_you_start: raw.before_you_start ?? [],
    steps: raw.steps.map(step),
    fees: (raw.fees ?? []).map((f) => ({ ...f, note: f.note ?? null })),
    contacts: (raw.contacts ?? []).map((c) => ({
      ...c,
      phone: c.phone ?? null,
      email: c.email ?? null,
      url: c.url ?? null,
      hours: c.hours ?? null,
      note: c.note ?? null,
    })),
    watch_out: raw.watch_out ?? [],
    gaps: raw.gaps ?? [],
    forms: (raw.forms ?? []).flatMap((id) => FORMS.get(id) ?? []),
    // Public pages say when the guide was gathered; "checked by our team" is for the app.
    checked: { verified: false, verified_at: null },
    state,
    path: where.path,
    ref: `approval-${raw.kind.toLowerCase().replaceAll("_", "-")}`,
  };
}

/** Every guide, in plan order (as the API sorts them). */
export const PUBLIC_GUIDES: PublicGuide[] = (guideFile.guides as unknown as RawGuide[])
  .map(normalise)
  .sort((a, b) => a.order - b.order || a.title.localeCompare(b.title));

/** The states and territories, then Australia-wide (Commonwealth) guides. */
export const GUIDE_STATES: GuideState[] = STATES;

export const NATIONAL = "australia";

export function guideState(segment: string): GuideState | undefined {
  return STATES.find((s) => s.segment === segment);
}

export function publicGuide(state: string, slug: string): PublicGuide | undefined {
  return PUBLIC_GUIDES.find((g) => g.state.segment === state && g.slug === slug);
}

/** A state's own guides for one scenario, then the Australia-wide ones that also apply. */
export function guidesFor(
  state: string,
  vertical: string,
): { local: PublicGuide[]; national: PublicGuide[] } {
  const inScenario = (g: PublicGuide) => g.verticals.includes(vertical as never);
  return {
    local: PUBLIC_GUIDES.filter((g) => g.state.segment === state && inScenario(g)),
    national:
      state === NATIONAL
        ? []
        : PUBLIC_GUIDES.filter((g) => g.state.segment === NATIONAL && inScenario(g)),
  };
}

/** Other guides someone reading this one will want: same state and scenario first. */
export function relatedGuides(guide: PublicGuide, limit = 6): PublicGuide[] {
  const vertical = guide.verticals[0];
  const { local, national } = guidesFor(guide.state.segment, vertical ?? "");
  return [...local, ...national].filter((g) => g.kind !== guide.kind).slice(0, limit);
}

/** "Australia-wide" reads oddly in a sentence ("in Australia-wide"). */
export function placeName(state: GuideState): string {
  return state.segment === NATIONAL ? "Australia" : state.name;
}

/** The first sentence of a text, cut at a word to `limit` characters. */
export function firstSentence(text: string, limit = 160): string {
  const match = /^(.+?[.!?])(\s|$)/.exec(text);
  const sentence = match?.[1] ?? text;
  if (sentence.length <= limit) return sentence;
  const cut = sentence.slice(0, limit - 1);
  return `${cut.slice(0, cut.lastIndexOf(" ")).replace(/[ ,.;:]+$/, "")}…`;
}

/** The search result snippet: what the guide answers, in one or two sentences. */
export function metaDescription(guide: PublicGuide): string {
  const lead = firstSentence(guide.summary, 155);
  if (lead.length > 110 || !guide.cost_summary) return lead;
  return firstSentence(`${lead} ${guide.cost_summary}`, 155);
}

/** A page title that names the place, unless the guide's own title already does. */
export function pageTitle(guide: PublicGuide): string {
  const place = placeName(guide.state);
  const named =
    guide.title.includes(place) ||
    guide.title.includes(`(${guide.state.code})`) ||
    guide.title.includes(` ${guide.state.code}`) ||
    /Cairns|ASIC|ATO|AUSTRAC|Australia/.test(guide.title);
  return named ? guide.title : `${guide.title} (${place})`;
}

export type CardFormat = "square" | "portrait" | "wide";

/** Where a guide's image card is served (`/guide-cards/<ref>[.format].jpg`). */
export function cardPath(guide: { ref: string }, format: CardFormat = "square"): string {
  return `/guide-cards/${guide.ref}${format === "square" ? "" : `.${format}`}.jpg`;
}

export const CARD_SIZES: Record<CardFormat, { width: number; height: number }> = {
  square: { width: 1080, height: 1080 },
  portrait: { width: 1080, height: 1350 },
  wide: { width: 1200, height: 630 },
};

/** What the card shows, for its alt text (the API's `cards.alt_text` says the same). */
export function cardAlt(guide: PublicGuide): string {
  const facts = [`${guide.steps.length} steps`];
  if (guide.forms.length > 0) {
    facts.push(`${guide.forms.length} official form${guide.forms.length === 1 ? "" : "s"}`);
  }
  facts.push("Costs and contacts");
  return `ApprovalReady step-by-step guide for ${guide.state.name}: ${guide.title}. ${facts.join(", ")}.`;
}

export interface Faq {
  question: string;
  answer: string;
}

function sentenceList(items: string[]): string {
  return items.map((i) => i.trim().replace(/[.;]?$/, ".")).join(" ");
}

/**
 * The questions people search for about an approval, each answered from the guide itself:
 * shown on the page and given to search engines as FAQ data, so answers come straight from
 * the guide's own (sourced) text.
 */
export function guideFaqs(guide: PublicGuide): Faq[] {
  const faqs: Faq[] = [{ question: "Do I need it, and how do I get it?", answer: guide.summary }];
  if (guide.cost_summary) {
    const fees = guide.fees
      .slice(0, 4)
      .map((f) => `${f.label}: ${f.amount}`)
      .join("; ");
    faqs.push({
      question: "How much does it cost?",
      answer: fees ? `${guide.cost_summary} Fees: ${fees}.` : guide.cost_summary,
    });
  }
  if (guide.timeframe) {
    faqs.push({ question: "How long does it take?", answer: guide.timeframe });
  }
  faqs.push({
    question: "Who issues it?",
    answer: `${guide.authority}.`.replace(/\.\.$/, "."),
  });
  if (guide.forms.length > 0) {
    faqs.push({
      question: "Which forms do I need?",
      answer: sentenceList(
        guide.forms.map((f) => {
          const label = f.code && !f.name.includes(f.code) ? `${f.code} ${f.name}` : f.name;
          return `${label} (${f.publisher}), at ${f.url}`;
        }),
      ),
    });
  }
  if (guide.before_you_start.length > 0) {
    faqs.push({
      question: "What do I need before I start?",
      answer: sentenceList(guide.before_you_start.slice(0, 5)),
    });
  }
  const phones = guide.contacts.filter((c) => c.phone || c.email || c.url);
  if (phones.length > 0) {
    faqs.push({
      question: "Who do I contact with questions?",
      answer: sentenceList(
        phones
          .slice(0, 3)
          .map((c) => [c.name, c.phone, c.email, c.url].filter(Boolean).join(", ")),
      ),
    });
  }
  if (guide.watch_out.length > 0) {
    faqs.push({
      question: "What commonly goes wrong?",
      answer: sentenceList(guide.watch_out.slice(0, 4)),
    });
  }
  return faqs;
}

const ORGANISATION = (site: string) => ({
  "@type": "Organization",
  "@id": `${site}/#organization`,
  name: "ApprovalReady",
  url: site,
  logo: `${site}/brand/approvalready-lockup.svg`,
});

/** Structured data for a guide page: the article, its steps, its FAQs and where it sits. */
export function guideJsonLd(guide: PublicGuide, site: string): Record<string, unknown> {
  const url = `${site}${guide.path}`;
  const image = `${site}${cardPath(guide, "wide")}`;
  const place = placeName(guide.state);
  return {
    "@context": "https://schema.org",
    "@graph": [
      {
        "@type": "Article",
        "@id": `${url}#article`,
        headline: pageTitle(guide),
        description: metaDescription(guide),
        image: [image, `${site}${cardPath(guide, "square")}`],
        datePublished: guide.checked_on,
        dateModified: guide.checked_on,
        inLanguage: "en-AU",
        author: { "@id": `${site}/#organization` },
        publisher: { "@id": `${site}/#organization` },
        mainEntityOfPage: url,
        about: { "@type": "GovernmentPermit", name: guide.title, issuedBy: guide.authority },
        spatialCoverage: { "@type": "Place", name: place === "Australia" ? place : `${place}, Australia` },
        citation: guide.sources.map((s) => ({ "@type": "WebPage", name: s.title, url: s.url })),
      },
      {
        "@type": "HowTo",
        "@id": `${url}#howto`,
        name: pageTitle(guide),
        description: guide.summary,
        image,
        ...(guide.cost_summary
          ? { estimatedCost: { "@type": "MonetaryAmount", currency: "AUD", description: guide.cost_summary } }
          : {}),
        supply: guide.before_you_start.map((text) => ({ "@type": "HowToSupply", name: text })),
        step: guide.steps.map((s, i) => ({
          "@type": "HowToStep",
          position: i + 1,
          name: s.title,
          text: s.detail,
          url: `${url}#step-${i + 1}`,
        })),
      },
      {
        "@type": "FAQPage",
        "@id": `${url}#faq`,
        mainEntity: guideFaqs(guide).map((f) => ({
          "@type": "Question",
          name: f.question,
          acceptedAnswer: { "@type": "Answer", text: f.answer },
        })),
      },
      {
        "@type": "BreadcrumbList",
        itemListElement: [
          { "@type": "ListItem", position: 1, name: "Guides", item: `${site}/guides` },
          {
            "@type": "ListItem",
            position: 2,
            name: guide.state.name,
            item: `${site}/guides/${guide.state.segment}`,
          },
          { "@type": "ListItem", position: 3, name: guide.title, item: url },
        ],
      },
      ORGANISATION(site),
    ],
  };
}

/** Structured data for a state's hub page: the list of its guides. */
export function stateJsonLd(state: GuideState, guides: PublicGuide[], site: string) {
  const url = `${site}/guides/${state.segment}`;
  return {
    "@context": "https://schema.org",
    "@graph": [
      {
        "@type": "CollectionPage",
        "@id": url,
        name: `Approval guides for ${placeName(state)}`,
        inLanguage: "en-AU",
        publisher: { "@id": `${site}/#organization` },
        mainEntity: {
          "@type": "ItemList",
          itemListElement: guides.map((g, i) => ({
            "@type": "ListItem",
            position: i + 1,
            name: g.title,
            url: `${site}${g.path}`,
          })),
        },
      },
      {
        "@type": "BreadcrumbList",
        itemListElement: [
          { "@type": "ListItem", position: 1, name: "Guides", item: `${site}/guides` },
          { "@type": "ListItem", position: 2, name: state.name, item: url },
        ],
      },
      ORGANISATION(site),
    ],
  };
}

/** JSON for a `<script type="application/ld+json">`, safe inside HTML. */
export function jsonLdScript(data: unknown): string {
  return JSON.stringify(data).replace(/</g, "\\u003c");
}
