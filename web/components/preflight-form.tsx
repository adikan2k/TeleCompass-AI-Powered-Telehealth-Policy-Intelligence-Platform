"use client";

import { useEffect, useRef, useState } from "react";

import { DecisionView } from "@/components/decision-view";
import { Button } from "@/components/ui/button";
import type { Decision, Options, VisitInput } from "@/lib/api";

// The date slider runs month by month over this range.
const FIRST_MONTH = { year: 2026, month: 1 };
const MONTHS = 36;

const LABELS: Record<string, string> = {
  live_video: "Live video",
  audio_only: "Phone (audio only)",
  store_and_forward: "Store and forward",
  remote_patient_monitoring: "Remote patient monitoring",
  medicaid: "Medicaid",
  medicare: "Medicare",
  private: "Private plan",
  self_pay: "Self-pay",
  behavioral_health: "Mental or behavioral health",
  other: "Other care",
  none: "No prescription",
  not_controlled: "A medicine that is not a controlled substance",
  II: "Schedule II (many ADHD stimulants are in this schedule)",
  III: "Schedule III",
  IV: "Schedule IV",
  V: "Schedule V",
};

const START: VisitInput = {
  profession: "psychiatrist",
  licensed_in: ["NY"],
  registered_in_patient_state: false,
  patient_state: "FL",
  modality: "audio_only",
  payer: "medicaid",
  service_category: "behavioral_health",
  prescription: "II",
  visit_date: "2026-12-01",
};

function label(value: string): string {
  return LABELS[value] ?? value.charAt(0).toUpperCase() + value.slice(1);
}

function monthToDate(index: number): string {
  const total = FIRST_MONTH.month - 1 + index;
  const year = FIRST_MONTH.year + Math.floor(total / 12);
  return `${year}-${String((total % 12) + 1).padStart(2, "0")}-01`;
}

function dateToMonth(value: string): number {
  const [year, month] = value.split("-").map(Number);
  const index = (year - FIRST_MONTH.year) * 12 + (month - FIRST_MONTH.month);
  return Math.min(Math.max(index, 0), MONTHS - 1);
}

const field = "mt-1 w-full rounded-md border border-input bg-card px-3 py-2 text-sm";
const legend = "text-sm font-semibold";

export function PreflightForm() {
  const [options, setOptions] = useState<Options | null>(null);
  const [visit, setVisit] = useState<VisitInput>(START);
  const [decision, setDecision] = useState<Decision | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const latest = useRef(0);

  useEffect(() => {
    fetch("/api/options")
      .then((response) => response.json())
      .then((body) => (body.error ? setProblem(body.error) : setOptions(body)))
      .catch(() => setProblem("The service is not reachable right now."));
  }, []);

  async function run(next: VisitInput) {
    const call = ++latest.current;
    setBusy(true);
    setProblem(null);
    setCopied(false);
    try {
      const response = await fetch("/api/preflight", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(next),
      });
      const body = await response.json();
      if (call !== latest.current) return; // a newer run has started; drop this answer
      if (!response.ok) {
        setProblem(body.error ?? "That visit could not be checked. Please review the form.");
      } else {
        setDecision(body);
      }
    } catch {
      if (call === latest.current) setProblem("The service is not reachable right now.");
    } finally {
      if (call === latest.current) setBusy(false);
    }
  }

  function change(patch: Partial<VisitInput>, rerun = false) {
    const next = { ...visit, ...patch };
    setVisit(next);
    if (rerun && decision) void run(next);
  }

  function toggleLicense(code: string) {
    const has = visit.licensed_in.includes(code);
    change({
      licensed_in: has
        ? visit.licensed_in.filter((item) => item !== code)
        : [...visit.licensed_in, code].sort(),
    });
  }

  async function copyLink() {
    if (!decision) return;
    await navigator.clipboard.writeText(`${window.location.origin}/d/${decision.id}`);
    setCopied(true);
  }

  if (!options) {
    return <p className="text-sm text-muted-foreground">{problem ?? "Loading the form…"}</p>;
  }

  const unlicensed = options.states.filter((state) => !visit.licensed_in.includes(state.code));

  return (
    <div className="grid gap-8 lg:grid-cols-[22rem_1fr]">
      <form
        className="space-y-5 self-start rounded-lg border border-border bg-card p-4"
        onSubmit={(event) => {
          event.preventDefault();
          void run(visit);
        }}
      >
        <label className="block">
          <span className={legend}>Clinician</span>
          <select
            className={field}
            value={visit.profession}
            onChange={(event) => change({ profession: event.target.value })}
          >
            {options.professions.map((item) => (
              <option key={item} value={item}>
                {label(item)}
              </option>
            ))}
          </select>
        </label>

        <fieldset>
          <legend className={legend}>Licensed in</legend>
          <ul className="mt-1 flex flex-wrap gap-1.5">
            {visit.licensed_in.map((code) => (
              <li key={code}>
                <button
                  type="button"
                  onClick={() => toggleLicense(code)}
                  className="rounded-md border border-primary bg-accent px-2 py-1 text-sm font-medium text-accent-foreground"
                  aria-label={`Remove ${code}`}
                >
                  {code} <span aria-hidden="true">×</span>
                </button>
              </li>
            ))}
            {visit.licensed_in.length === 0 ? (
              <li className="text-sm text-muted-foreground">No state yet</li>
            ) : null}
          </ul>
          <select
            className={field}
            value=""
            aria-label="Add a state the clinician is licensed in"
            onChange={(event) => event.target.value && toggleLicense(event.target.value)}
          >
            <option value="">Add a state…</option>
            {unlicensed.map((state) => (
              <option key={state.code} value={state.code}>
                {state.name}
              </option>
            ))}
          </select>
        </fieldset>

        <label className="block">
          <span className={legend}>Patient is in</span>
          <select
            className={field}
            value={visit.patient_state}
            onChange={(event) => change({ patient_state: event.target.value })}
          >
            {options.patient_states.map((state) => (
              <option key={state.code} value={state.code}>
                {state.name}
              </option>
            ))}
          </select>
          <span className="mt-1 block text-xs text-muted-foreground">
            Only states whose law has been read are listed. More are on the way.
          </span>
        </label>

        <label className="flex items-start gap-2 text-sm">
          <input
            type="checkbox"
            className="mt-1 size-4"
            checked={visit.registered_in_patient_state}
            onChange={(event) => change({ registered_in_patient_state: event.target.checked })}
          />
          <span>The clinician holds that state’s out-of-state telehealth registration</span>
        </label>

        <label className="block">
          <span className={legend}>How the visit happens</span>
          <select
            className={field}
            value={visit.modality}
            onChange={(event) => change({ modality: event.target.value })}
          >
            {options.modalities.map((item) => (
              <option key={item} value={item}>
                {label(item)}
              </option>
            ))}
          </select>
        </label>

        <label className="block">
          <span className={legend}>Who pays</span>
          <select
            className={field}
            value={visit.payer}
            onChange={(event) => change({ payer: event.target.value })}
          >
            {options.payers.map((item) => (
              <option key={item} value={item}>
                {label(item)}
              </option>
            ))}
          </select>
        </label>

        <label className="block">
          <span className={legend}>Kind of care</span>
          <select
            className={field}
            value={visit.service_category}
            onChange={(event) => change({ service_category: event.target.value })}
          >
            {options.service_categories.map((item) => (
              <option key={item} value={item}>
                {label(item)}
              </option>
            ))}
          </select>
        </label>

        <label className="block">
          <span className={legend}>Prescription</span>
          <select
            className={field}
            value={visit.prescription}
            onChange={(event) => change({ prescription: event.target.value })}
          >
            {options.prescriptions.map((item) => (
              <option key={item} value={item}>
                {label(item)}
              </option>
            ))}
          </select>
        </label>

        <div>
          <label className="block">
            <span className={legend}>Date of the visit</span>
            <input
              type="date"
              className={field}
              value={visit.visit_date}
              min="2015-01-01"
              max="2035-12-31"
              onChange={(event) => event.target.value && change({ visit_date: event.target.value })}
            />
          </label>
          <label className="mt-2 block text-xs text-muted-foreground">
            Slide through time, month by month (Jan 2026 to Dec 2028)
            <input
              type="range"
              className="mt-1 w-full accent-primary"
              min={0}
              max={MONTHS - 1}
              value={dateToMonth(visit.visit_date)}
              onChange={(event) =>
                change({ visit_date: monthToDate(Number(event.target.value)) }, true)
              }
            />
          </label>
        </div>

        <Button type="submit" size="lg" className="w-full" disabled={busy}>
          {busy ? "Checking…" : "Run the preflight"}
        </Button>
        <p className="text-xs text-muted-foreground">
          The form has no box to type in, on purpose: it cannot hold a name or any patient detail.
        </p>
      </form>

      <section aria-live="polite" className="min-w-0">
        {problem ? (
          <p role="alert" className="rounded-md border-2 border-stop bg-stop-soft p-3 text-sm">
            <span className="font-semibold">Problem: </span>
            {problem}
          </p>
        ) : null}
        {decision ? (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-3 rounded-md border border-border bg-card p-3">
              <a
                href={`/d/${decision.id}`}
                className="text-sm font-medium text-primary underline underline-offset-2"
              >
                Link to this answer
              </a>
              <Button type="button" variant="outline" size="sm" onClick={copyLink}>
                {copied ? "Copied" : "Copy the link"}
              </Button>
              <span className="text-xs text-muted-foreground">
                The link always shows this exact answer, with the rules it rested on.
              </span>
            </div>
            <DecisionView decision={decision} />
          </div>
        ) : problem ? null : (
          <div className="rounded-lg border border-dashed border-input p-6 text-sm text-muted-foreground">
            <p className="font-medium text-foreground">The form starts with an example.</p>
            <p className="mt-1">
              A psychiatrist licensed in New York, a patient in Florida, a phone visit paid by
              Medicaid, and a Schedule II prescription. Press “Run the preflight” to see each
              answer with the words of the law behind it, then move the date.
            </p>
          </div>
        )}
      </section>
    </div>
  );
}
