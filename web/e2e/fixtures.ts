import type { Page, Route } from "@playwright/test";

// Invented answers in the API's shape. The law text here is made up for the tests.
const notice = { not_legal_advice: "Not legal advice.", sources_last_fetched: "2026-11-27" };

export const options = {
  patient_states: [{ code: "FL", name: "Florida" }],
  states: [
    { code: "FL", name: "Florida" },
    { code: "NY", name: "New York" },
    { code: "TX", name: "Texas" },
  ],
  professions: ["psychiatrist", "physician", "counselor"],
  modalities: ["live_video", "audio_only", "store_and_forward", "remote_patient_monitoring"],
  payers: ["medicaid", "medicare", "private", "self_pay"],
  service_categories: ["behavioral_health", "other"],
  prescriptions: ["none", "not_controlled", "II", "III", "IV", "V"],
  notice,
};

function rule(id: number, summary: string, quote: string, dates: { from?: string; to?: string } = {}) {
  return {
    rule_id: id,
    summary,
    quote,
    source_url: "https://example.org/invented-code/59-1",
    source_fetched: "2026-11-27",
    status: "draft",
    conditions: [],
    effective_from: dates.from ?? null,
    effective_to: dates.to ?? null,
    auto_review: "right",
  };
}

const NO_PHONE = rule(
  1,
  "Medicaid does not pay for telephone calls.",
  "(5) Exclusion. The programme does not reimburse telephone conversations.",
);
const VIDEO = rule(2, "Medicaid pays for live video.", "(4) Coverage. The programme reimburses live, two-way video.");
const ANYWHERE = rule(
  3,
  "Patients may be anywhere until the end of 2027.",
  "Through December 31, 2027, patients may receive telehealth anywhere.",
  { to: "2027-12-31" },
);
const IN_PERSON = rule(
  4,
  "An in-person visit is required for mental health telehealth.",
  "Starting January 1, 2028, an in-person visit is required.",
  { from: "2028-01-01" },
);

export function decision(date: string, id: string | null) {
  const after = date >= "2028-01-01";
  return {
    id,
    created_at: "2026-11-27T10:00:00+00:00",
    visit: {},
    summary: `psychiatrist licensed in NY; patient in FL; audio only; payer medicaid; on ${date}`,
    lines: [
      {
        key: "cross_state_licensure",
        title: "Cross-state licensure",
        verdict: "not_allowed",
        reason: "The clinician has no FL licence and no FL telehealth registration.",
        evidence: [],
        conditions: [],
        would_allow: [rule(5, "May register as an out-of-state provider.", "A provider may register.")],
      },
      {
        key: "medicaid_modality",
        title: "Medicaid payment for this modality",
        verdict: "not_allowed",
        reason: "Not payable: a rule excludes audio only.",
        evidence: [NO_PHONE],
        conditions: [],
        would_allow: [VIDEO],
      },
      {
        key: "consent",
        title: "Patient consent",
        verdict: "silent",
        reason: "We hold no FL rule that requires consent for a telehealth visit.",
        evidence: [],
        conditions: [],
        would_allow: [],
      },
      {
        key: "medicare_originating_site",
        title: "Medicare: where the patient can be (for reference: the payer is not Medicare)",
        verdict: after ? "silent" : "allowed",
        reason: after ? "No rule we hold is in force on 2028-01-01." : `Allowed on ${date}.`,
        evidence: after ? [] : [ANYWHERE],
        conditions: [],
        would_allow: after ? [ANYWHERE] : [],
      },
      {
        key: "medicare_in_person_requirement",
        title: "Medicare: in-person visit requirement (for reference: the payer is not Medicare)",
        verdict: after ? "allowed_with_conditions" : "allowed",
        reason: after ? `A requirement is in force on ${date}.` : "No requirement we hold is in force yet.",
        evidence: after ? [] : [IN_PERSON],
        conditions: after ? [IN_PERSON] : [],
        would_allow: [],
      },
    ],
    notice,
  };
}

export type Calls = { body: Record<string, unknown>; store: boolean }[];

/** Mock the site's own /api routes. Returns the list of preflight calls made. */
export async function mockApi(page: Page, failPreflight = false): Promise<Calls> {
  const calls: Calls = [];
  await page.route("**/api/options", (route) => route.fulfill({ json: options }));
  await page.route(/\/api\/preflight(\?.*)?$/, async (route: Route) => {
    const body = route.request().postDataJSON() as Record<string, unknown>;
    const store = !route.request().url().includes("store=false");
    calls.push({ body, store });
    if (failPreflight) {
      await route.fulfill({ status: 500, json: { error: "The check failed on the server." } });
      return;
    }
    await route.fulfill({ json: decision(String(body.visit_date), store ? "Ab3xY9pQ2mZk" : null) });
  });
  return calls;
}
