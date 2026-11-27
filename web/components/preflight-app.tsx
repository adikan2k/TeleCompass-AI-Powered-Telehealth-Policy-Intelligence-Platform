"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { type Change, Checklist } from "@/components/checklist";
import { type Mark, TimeTape } from "@/components/time-tape";
import ClickSpark from "@/components/vendor/ClickSpark";
import type { Decision, Options, Verdict, VisitInput } from "@/lib/api";
import { dayAfter, monthName, yearOf } from "@/lib/format";

const LABELS: Record<string, string> = {
  live_video: "Live video",
  audio_only: "Phone only",
  store_and_forward: "Store and forward",
  remote_patient_monitoring: "Remote monitoring",
  medicaid: "Medicaid",
  medicare: "Medicare",
  private: "Private plan",
  self_pay: "Self-pay",
  behavioral_health: "Mental or behavioral health",
  other: "Other care",
  none: "No prescription",
  not_controlled: "Not a controlled substance",
  II: "Schedule II (most ADHD stimulants)",
  III: "Schedule III",
  IV: "Schedule IV",
  V: "Schedule V",
};

// The worked example the page opens on: invented, and never stored.
const EXAMPLE: VisitInput = {
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

const TAPE_START = "2026-01-01";
const TAPE_END = "2028-12-31";
const RERUN_DELAY = 250;

function label(value: string): string {
  return LABELS[value] ?? value.charAt(0).toUpperCase() + value.slice(1);
}

function withoutDate(visit: VisitInput): string {
  return JSON.stringify({ ...visit, visit_date: null });
}

/** Dates in this answer where a rule starts or ends, counted by distinct rule. */
function marksOf(decision: Decision | null): Mark[] {
  if (!decision) return [];
  const byDate = new Map<string, Set<number>>();
  for (const line of decision.lines) {
    for (const rule of [...line.evidence, ...line.conditions, ...line.would_allow]) {
      const dates = [rule.effective_from, rule.effective_to ? dayAfter(rule.effective_to) : null];
      for (const date of dates) {
        if (!date || date < TAPE_START || date > TAPE_END) continue;
        if (!byDate.has(date)) byDate.set(date, new Set());
        byDate.get(date)!.add(rule.rule_id);
      }
    }
  }
  return [...byDate.entries()]
    .map(([date, ids]) => ({ date, count: ids.size }))
    .sort((a, b) => a.date.localeCompare(b.date));
}

function Segmented({
  legend,
  name,
  options,
  value,
  onChange,
  columns = 2,
}: {
  legend: string;
  name: string;
  options: string[];
  value: string;
  onChange: (value: string) => void;
  columns?: number;
}) {
  return (
    <fieldset>
      <legend className="mb-1.5 text-[14px] font-semibold">{legend}</legend>
      <div
        className="grid gap-px border border-rule-strong bg-rule-strong"
        style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }}
      >
        {options.map((option) => {
          const checked = option === value;
          return (
            <label
              key={option}
              className={`press relative flex min-h-11 cursor-pointer items-center gap-2 px-3 py-2 text-[14px] leading-tight has-[input:focus-visible]:z-10 has-[input:focus-visible]:outline-2 has-[input:focus-visible]:outline-offset-2 has-[input:focus-visible]:outline-signal ${checked ? "bg-ink font-medium text-white" : "bg-sheet text-ink hover:bg-paper"}`}
            >
              <input
                type="radio"
                name={name}
                value={option}
                checked={checked}
                onChange={() => onChange(option)}
                className="sr-only"
              />
              <span
                aria-hidden="true"
                className={`size-2 shrink-0 rotate-45 border ${checked ? "border-signal bg-signal" : "border-rule-strong"}`}
              />
              {label(option)}
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}

const selectClass =
  "mt-1.5 block min-h-11 w-full border border-rule-strong bg-sheet px-3 text-[15px] hover:border-ink";

export function PreflightApp() {
  const [options, setOptions] = useState<Options | null>(null);
  const [visit, setVisit] = useState<VisitInput>(EXAMPLE);
  const [decision, setDecision] = useState<Decision | null>(null);
  const [answered, setAnswered] = useState<VisitInput | null>(null);
  const [changes, setChanges] = useState<Record<string, Change>>({});
  const [runKey, setRunKey] = useState("none");
  const [firstRun, setFirstRun] = useState(true);
  const [userChecked, setUserChecked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [slow, setSlow] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const latest = useRef(0);
  const rerunTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const run = useCallback(
    async (next: VisitInput, store: boolean, previous: { decision: Decision; visit: VisitInput } | null) => {
      const call = ++latest.current;
      setBusy(true);
      setProblem(null);
      const slowTimer = setTimeout(() => call === latest.current && setSlow(true), 300);
      try {
        const response = await fetch(`/api/preflight${store ? "" : "?store=false"}`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(next),
        });
        const body = await response.json();
        if (call !== latest.current) return; // a newer check has started; drop this answer
        if (!response.ok) {
          setProblem(body.error ?? "That visit could not be checked. Review the choices and try again.");
          return;
        }
        const sameVisit = previous && withoutDate(previous.visit) === withoutDate(next);
        const found: Record<string, Change> = {};
        if (sameVisit && previous.visit.visit_date !== next.visit_date) {
          const before = new Map<string, Verdict>(
            previous.decision.lines.map((line) => [line.key, line.verdict]),
          );
          const when = `${monthName(previous.visit.visit_date)} ${yearOf(previous.visit.visit_date)}`;
          for (const line of body.lines as Decision["lines"]) {
            const was = before.get(line.key);
            if (was && was !== line.verdict) found[line.key] = { from: was, when };
          }
        }
        setChanges(found);
        setFirstRun(!sameVisit);
        setDecision(body);
        setAnswered(next);
        setCopied(false);
        setRunKey(`${call}`);
      } catch {
        if (call === latest.current) setProblem("The service is not reachable right now. Try again in a minute.");
      } finally {
        clearTimeout(slowTimer);
        if (call === latest.current) {
          setBusy(false);
          setSlow(false);
        }
      }
    },
    [],
  );

  useEffect(() => {
    let cancelled = false;
    fetch("/api/options")
      .then((response) => response.json())
      .then((body) => {
        if (cancelled) return;
        if (body.error) {
          setProblem(body.error);
          return;
        }
        setOptions(body);
        void run(EXAMPLE, false, null);
      })
      .catch(() => !cancelled && setProblem("The service is not reachable right now. Try again in a minute."));
    return () => {
      cancelled = true;
    };
  }, [run]);

  useEffect(() => () => {
    if (rerunTimer.current) clearTimeout(rerunTimer.current);
  }, []);

  const marks = useMemo(() => marksOf(decision), [decision]);
  const stale = answered !== null && withoutDate(answered) !== withoutDate(visit);

  function change(patch: Partial<VisitInput>) {
    setVisit((current) => ({ ...current, ...patch }));
  }

  function changeDate(iso: string) {
    const next = { ...visit, visit_date: iso };
    setVisit(next);
    if (!decision || !answered || stale) return;
    if (rerunTimer.current) clearTimeout(rerunTimer.current);
    const previous = { decision, visit: answered };
    rerunTimer.current = setTimeout(() => void run(next, userChecked, previous), RERUN_DELAY);
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
    if (!decision?.id) return;
    await navigator.clipboard.writeText(`${window.location.origin}/d/${decision.id}`);
    setCopied(true);
  }

  const stateName = (code: string) => options?.states.find((state) => state.code === code)?.name ?? code;
  const unlicensed = options?.states.filter((state) => !visit.licensed_in.includes(state.code)) ?? [];

  return (
    <div className="grid items-start gap-6 lg:grid-cols-[21rem_minmax(0,1fr)] lg:gap-8">
      <form
        aria-labelledby="visit-heading"
        className="order-2 space-y-5 border border-rule bg-sheet p-4 sm:p-5 lg:sticky lg:top-4 lg:order-1"
        onSubmit={(event) => {
          event.preventDefault();
          setUserChecked(true);
          void run(visit, true, null);
        }}
      >
        <div>
          <h2 id="visit-heading" className="text-[20px] font-semibold">
            The visit
          </h2>
          <p className="mt-1 text-[14px] text-ink-soft">
            Fixed choices only. There is nowhere to type a name or a patient detail.
          </p>
        </div>

        <label className="block">
          <span className="text-[14px] font-semibold">Clinician</span>
          <select
            className={selectClass}
            value={visit.profession}
            onChange={(event) => change({ profession: event.target.value })}
            disabled={!options}
          >
            {(options?.professions ?? [visit.profession]).map((item) => (
              <option key={item} value={item}>
                {label(item)}
              </option>
            ))}
          </select>
        </label>

        <fieldset>
          <legend className="text-[14px] font-semibold">Licensed in</legend>
          <ul className="mt-1.5 flex flex-wrap gap-1.5" aria-live="polite">
            {visit.licensed_in.map((code) => (
              <li key={code}>
                <button
                  type="button"
                  onClick={() => toggleLicense(code)}
                  className="press notch inline-flex min-h-9 items-center gap-1.5 border border-ink bg-paper py-1 pr-3 pl-2 text-[14px] font-medium"
                  aria-label={`Remove ${stateName(code)}`}
                >
                  {stateName(code)}
                  <span aria-hidden="true" className="text-ink-soft">
                    ×
                  </span>
                </button>
              </li>
            ))}
            {visit.licensed_in.length === 0 ? (
              <li className="text-[14px] text-ink-soft">No state chosen yet</li>
            ) : null}
          </ul>
          <select
            className={selectClass}
            value=""
            aria-label="Add a state the clinician is licensed in"
            onChange={(event) => event.target.value && toggleLicense(event.target.value)}
            disabled={!options}
          >
            <option value="">Add a state</option>
            {unlicensed.map((state) => (
              <option key={state.code} value={state.code}>
                {state.name}
              </option>
            ))}
          </select>
        </fieldset>

        <div>
          <label className="block">
            <span className="text-[14px] font-semibold">Patient is in</span>
            <select
              className={selectClass}
              value={visit.patient_state}
              onChange={(event) => change({ patient_state: event.target.value })}
              disabled={!options}
            >
              {(options?.patient_states ?? [{ code: "FL", name: "Florida" }]).map((state) => (
                <option key={state.code} value={state.code}>
                  {state.name}
                </option>
              ))}
            </select>
          </label>
          <p className="mt-1 text-[13px] text-ink-soft">Only states whose law has been read are listed.</p>
          <label className="mt-3 flex items-start gap-2.5 text-[14px]">
            <input
              type="checkbox"
              className="mt-0.5 size-4 accent-ink"
              checked={visit.registered_in_patient_state}
              onChange={(event) => change({ registered_in_patient_state: event.target.checked })}
            />
            <span>The clinician holds that state’s out-of-state telehealth registration</span>
          </label>
        </div>

        <Segmented
          legend="How the visit happens"
          name="modality"
          options={options?.modalities ?? ["live_video", "audio_only", "store_and_forward", "remote_patient_monitoring"]}
          value={visit.modality}
          onChange={(value) => change({ modality: value })}
        />
        <Segmented
          legend="Who pays"
          name="payer"
          options={options?.payers ?? ["medicaid", "medicare", "private", "self_pay"]}
          value={visit.payer}
          onChange={(value) => change({ payer: value })}
        />
        <Segmented
          legend="Kind of care"
          name="care"
          options={options?.service_categories ?? ["behavioral_health", "other"]}
          value={visit.service_category}
          onChange={(value) => change({ service_category: value })}
          columns={1}
        />

        <label className="block">
          <span className="text-[14px] font-semibold">Prescription</span>
          <select
            className={selectClass}
            value={visit.prescription}
            onChange={(event) => change({ prescription: event.target.value })}
            disabled={!options}
          >
            {(options?.prescriptions ?? [visit.prescription]).map((item) => (
              <option key={item} value={item}>
                {label(item)}
              </option>
            ))}
          </select>
        </label>

        <div className="space-y-2 border-t border-rule pt-4">
          <button
            type="submit"
            disabled={!options}
            className="press notch-lg flex min-h-12 w-full items-center justify-between bg-ink px-4 text-[16px] font-semibold text-white hover:bg-[#23332f] disabled:opacity-50"
          >
            Check this visit
            <svg viewBox="0 0 20 20" className="size-4" aria-hidden="true">
              <path d="M4 10h11M11 5l5 5-5 5" fill="none" stroke="currentColor" strokeWidth="2" />
            </svg>
          </button>
          <p role="status" className="min-h-5 text-[13px] text-ink-soft">
            {slow ? "Checking against the stored law…" : ""}
          </p>
        </div>
      </form>

      <div className="order-1 min-w-0 space-y-6 lg:order-2">
        <TimeTape value={visit.visit_date} marks={marks} onChange={changeDate} />

        {problem ? (
          <div role="alert" className="border-2 border-stop bg-stop-soft p-4 text-[15px]">
            <p className="font-semibold">That did not work.</p>
            <p className="mt-1">{problem}</p>
          </div>
        ) : null}

        {stale ? (
          <div className="flex flex-wrap items-center justify-between gap-3 border border-signal bg-signal-soft p-4 text-[15px]">
            <p>The answer below is for the visit before your changes.</p>
            <button
              type="button"
              onClick={() => {
                setUserChecked(true);
                void run(visit, true, null);
              }}
              className="press notch min-h-11 bg-ink px-4 font-semibold text-white"
            >
              Check the changed visit
            </button>
          </div>
        ) : null}

        {decision ? (
          <>
            <div className="flex flex-wrap items-center justify-between gap-3 border-y border-rule py-3">
              {decision.id ? (
                <>
                  <p className="min-w-0 text-[14px]">
                    <span className="font-semibold">Saved.</span>{" "}
                    <a href={`/d/${decision.id}`} className="font-mono underline [overflow-wrap:anywhere]">
                      /d/{decision.id}
                    </a>{" "}
                    <span className="text-ink-soft">always shows this exact answer.</span>
                  </p>
                  <div className="inline-block">
                    <ClickSpark sparkColor="#e4570e" sparkCount={7} sparkSize={9} sparkRadius={20} duration={360}>
                      <button
                        type="button"
                        onClick={copyLink}
                        className="press min-h-11 border border-ink bg-sheet px-4 text-[14px] font-semibold"
                      >
                        {copied ? "Link copied" : "Copy the link"}
                      </button>
                    </ClickSpark>
                  </div>
                  <span className="sr-only" aria-live="polite">
                    {copied ? "Link copied" : ""}
                  </span>
                </>
              ) : (
                <p className="text-[14px] text-ink-soft">
                  <span className="font-semibold text-ink">A worked example, not saved.</span> Change the
                  visit or press Check this visit to save an answer with its own link.
                </p>
              )}
            </div>
            <Checklist
              key={answered ? withoutDate(answered) : "none"}
              decision={decision}
              runKey={runKey}
              changes={changes}
              firstRun={firstRun}
              busy={busy}
              startOpen={decision.id ? [] : ["medicaid_modality"]}
            />
          </>
        ) : problem ? null : (
          <div aria-hidden="true" className="border border-rule bg-sheet">
            {Array.from({ length: 5 }, (_, i) => (
              <div key={i} className="grid grid-cols-[2rem_1fr] gap-3 border-b border-rule px-5 py-5 last:border-0">
                <span className="size-6 rounded-full bg-paper" />
                <div className="space-y-2">
                  <span className="block h-4 w-2/5 bg-paper" />
                  <span className="block h-3 w-4/5 bg-paper" />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
