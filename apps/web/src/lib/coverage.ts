/** State and territory names by the code addresses use. */
export const STATE_NAMES: Record<string, string> = {
  QLD: "Queensland",
  NSW: "New South Wales",
  VIC: "Victoria",
  WA: "Western Australia",
  SA: "South Australia",
  TAS: "Tasmania",
  ACT: "Australian Capital Territory",
  NT: "Northern Territory",
};

/** The states and territories whose addresses and land parcels we look up (the API's
 * `Lookups.states`). Each state added there is added here. */
export const LOOKUP_STATE_CODES: readonly string[] = ["QLD"];
export const LOOKUP_STATES: readonly string[] = LOOKUP_STATE_CODES.map((c) => STATE_NAMES[c] ?? c);

/** "Queensland", "Queensland and New South Wales", "Queensland, New South Wales and Victoria". */
export function statesPhrase(states: readonly string[] = LOOKUP_STATES): string {
  if (states.length <= 1) return states[0] ?? "";
  return `${states.slice(0, -1).join(", ")} and ${states[states.length - 1]}`;
}

/** "the Queensland Government", "the ACT Government". */
export function stateGovernment(code: string): string {
  if (code === "ACT") return "the ACT Government";
  return `the ${STATE_NAMES[code] ?? code} Government`;
}
