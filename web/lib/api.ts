// What the TeleCompass API sends, and where the site's server finds it.
// The browser never calls the API directly: it calls this site, and this site calls the API.

export type Verdict = "allowed" | "allowed_with_conditions" | "not_allowed" | "silent" | "not_applicable";

export type Evidence = {
  rule_id: number;
  summary: string;
  quote: string;
  source_url: string | null;
  source_fetched: string | null;
  status: string;
  conditions: string[];
  effective_from: string | null;
  effective_to: string | null;
  auto_review: string | null;
};

export type Line = {
  key: string;
  title: string;
  verdict: Verdict;
  reason: string;
  evidence: Evidence[];
  conditions: Evidence[];
  would_allow: Evidence[];
};

export type Notice = { not_legal_advice: string; sources_last_fetched: string };

export type Decision = {
  id: string | null; // null for an answer that was shown but not stored
  created_at?: string;
  summary: string;
  lines: Line[];
  notice: Notice;
};

export type Options = {
  patient_states: { code: string; name: string }[];
  states: { code: string; name: string }[];
  professions: string[];
  modalities: string[];
  payers: string[];
  service_categories: string[];
  prescriptions: string[];
  notice: Notice;
};

export type VisitInput = {
  profession: string;
  licensed_in: string[];
  registered_in_patient_state: boolean;
  patient_state: string;
  modality: string;
  payer: string;
  service_category: string;
  prescription: string;
  visit_date: string;
};

export type RuleCard = {
  id: number;
  rule_type: string;
  rule_type_label: string;
  summary: string;
  quote: string | null;
  source_url: string | null;
  source_fetched_at: string | null;
  effective_from: string | null;
  effective_to: string | null;
};

export type PageChange = {
  kind: "added" | "removed" | "changed";
  category: string;
  topic: string;
  subtopic: string | null;
  rule_type_label: string | null;
  fields: string[];
  review: string;
};

export type Place = {
  code: string;
  name: string;
  page: {
    from: { captured_at: string; origin: string };
    to: { captured_at: string; origin: string };
    page_url: string | null;
    changes: PageChange[];
  } | null;
  rule_changes: {
    change: "added" | "retired";
    on: string | null;
    by: string | null;
    rule: RuleCard;
  }[];
  dates: {
    event: "starts" | "ends";
    on: string;
    past: boolean;
    rule: RuleCard;
  }[];
  law_changed: { url: string; detected_at: string }[];
};

export type Changes = {
  care: string;
  today: string;
  window: { from: string; to: string };
  not_held: string[];
  places: Place[];
  notice: Notice;
};

/** The API's address. Set API_URL where the site is hosted; locally it is the dev API. */
export function apiUrl(): string {
  return (process.env.API_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");
}
