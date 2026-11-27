"use client";

import { animate, createScope, stagger } from "animejs";
import { useEffect, useRef, useState } from "react";

import type { Changes, PageChange, Place, RuleCard } from "@/lib/api";
import { formatDate, hostOf } from "@/lib/format";

const CARE = [
  { value: "behavioral_health", label: "Mental health" },
  { value: "other", label: "Other care" },
];

// Each kind of page change has a sign, a word and a tint; the sign and word carry it alone.
const KINDS: Record<PageChange["kind"], { sign: string; word: string; tint: string }> = {
  added: { sign: "+", word: "New entry", tint: "bg-ok-soft text-ok" },
  removed: { sign: "−", word: "Entry removed", tint: "bg-stop-soft text-stop" },
  changed: { sign: "Δ", word: "Entry changed", tint: "bg-warn-soft text-warn" },
};

const ORIGINS: Record<string, string> = {
  wayback: "Internet Archive copy",
  live: "fetched by us",
};

function daysBetween(from: string, to: string): number {
  return Math.round((Date.parse(to.slice(0, 10)) - Date.parse(from.slice(0, 10))) / 86_400_000);
}

function inDays(today: string, on: string): string {
  const days = daysBetween(today, on);
  if (days === 0) return "today";
  if (days > 0) return days === 1 ? "tomorrow" : `in ${days} days`;
  return days === -1 ? "yesterday" : `${-days} days ago`;
}

function Quote({ rule }: { rule: RuleCard }) {
  if (!rule.quote) return null;
  return (
    <figure className="space-y-1.5">
      <blockquote className="law-quote border-l-2 border-ink bg-quote py-2 pr-3 pl-4 text-[15px] leading-relaxed">
        {rule.quote}
      </blockquote>
      {rule.source_url ? (
        <figcaption className="text-[13px] text-ink-soft">
          From{" "}
          <a className="font-mono underline" href={rule.source_url} target="_blank" rel="noreferrer">
            {hostOf(rule.source_url)}
          </a>
          {rule.source_fetched_at ? <>, fetched {formatDate(rule.source_fetched_at)}</> : null}
        </figcaption>
      ) : null}
    </figure>
  );
}

function PageSection({ code, page }: { code: string; page: NonNullable<Place["page"]> }) {
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 id={`page-${code}`} className="text-[18px] font-semibold">
          On the policy page
        </h3>
        {page.page_url ? (
          <a className="text-[13px] underline" href={page.page_url} target="_blank" rel="noreferrer">
            See the page at CCHP
          </a>
        ) : null}
      </div>
      <ol className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-x-3 border border-rule bg-sheet px-4 py-3 text-[14px]">
        <li className="contents">
          <span className="font-mono">{formatDate(page.from.captured_at)}</span>
          <span aria-hidden="true" className="relative h-px bg-rule-strong">
            <span className="absolute -top-[3px] right-0 size-[7px] rotate-45 border-t border-r border-ink" />
          </span>
          <span className="font-mono">{formatDate(page.to.captured_at)}</span>
        </li>
        <li className="contents text-[12.5px] text-ink-soft">
          <span>{ORIGINS[page.from.origin] ?? page.from.origin}</span>
          <span className="text-center">
            {daysBetween(page.from.captured_at, page.to.captured_at)} days apart
          </span>
          <span className="text-right">{ORIGINS[page.to.origin] ?? page.to.origin}</span>
        </li>
      </ol>
      {page.changes.length === 0 ? (
        <p className="text-[15px] text-ink-soft">Nothing in scope changed between these two copies.</p>
      ) : (
        <ul className="divide-y divide-rule border-y border-rule">
          {page.changes.map((change, index) => {
            const kind = KINDS[change.kind];
            return (
              <li key={index} data-row className="flex gap-3 py-3">
                <span
                  aria-hidden="true"
                  className={`notch grid size-8 shrink-0 place-items-center font-mono text-[17px] ${kind.tint}`}
                >
                  {kind.sign}
                </span>
                <div className="min-w-0 flex-1 space-y-0.5">
                  <p className="text-[15px] font-medium">
                    <span className="sr-only">{kind.word}: </span>
                    {change.category} · {change.topic}
                    {change.subtopic ? <span className="text-ink-soft"> · {change.subtopic}</span> : null}
                  </p>
                  <p className="text-[13px] text-ink-soft">
                    {kind.word}
                    {change.rule_type_label ? <> · feeds {change.rule_type_label.toLowerCase()}</> : null}
                  </p>
                </div>
                <span className="self-start border border-rule-strong px-2 py-0.5 text-[12.5px] whitespace-nowrap">
                  {change.review}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function RuleChanges({ code, items }: { code: string; items: Place["rule_changes"] }) {
  return (
    <div className="space-y-4">
      <h3 id={`rules-${code}`} className="text-[18px] font-semibold">
        Rule changes now live
      </h3>
      {items.length === 0 ? (
        <p className="text-[15px] text-ink-soft">
          No rule has been added or retired through review yet. A change reaches the answers only after a
          person approves it.
        </p>
      ) : (
        <ul className="space-y-4">
          {items.map((item) => (
            <li
              key={`${item.change}-${item.rule.id}`}
              data-row
              className="space-y-3 border border-rule bg-sheet p-4"
            >
              <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px]">
                <span
                  className={`notch py-0.5 pr-3 pl-2 font-semibold ${item.change === "added" ? "bg-ok-soft text-ok" : "bg-stop-soft text-stop"}`}
                >
                  {item.change === "added" ? "+ Added" : "− Retired"}
                </span>
                <span className="text-ink-soft">{item.rule.rule_type_label}</span>
                {item.on ? (
                  <span className="text-ink-soft">
                    {item.change === "added" ? "approved" : "from"}{" "}
                    <span className="font-mono">{formatDate(item.on)}</span>
                    {item.by ? <> by {item.by}</> : null}
                  </span>
                ) : null}
              </p>
              <p
                className={`text-[16px] font-medium ${item.change === "retired" ? "line-through decoration-1" : ""}`}
              >
                {item.rule.summary}
              </p>
              <Quote rule={item.rule} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function DatesAhead({ place, today }: { place: Place; today: string }) {
  return (
    <div className="space-y-4">
      <h3 id={`dates-${place.code}`} className="text-[18px] font-semibold">
        Dates ahead
      </h3>
      {place.dates.length === 0 ? (
        <p className="text-[15px] text-ink-soft">No live rule starts or ends in this window.</p>
      ) : (
        <ol className="relative space-y-5 border-l border-rule-strong pl-5">
          {place.dates.map((item) => (
            <li key={`${item.event}-${item.rule.id}`} data-row className="relative space-y-2">
              <span
                aria-hidden="true"
                className={`absolute top-[7px] -left-[25px] size-[9px] rotate-45 ${item.past ? "border border-ink bg-paper" : "bg-signal"}`}
              />
              <p className="flex flex-wrap items-baseline gap-x-2">
                <span className="font-mono text-[15px]">{formatDate(item.on)}</span>
                <span className="text-[13px] text-ink-soft">
                  {item.past ? (item.event === "ends" ? "ended" : "started") : item.event} ·{" "}
                  {inDays(today, item.on)}
                </span>
              </p>
              <p className="text-[15px]">{item.rule.summary}</p>
              <details className="group text-[14px]">
                <summary className="cursor-pointer underline decoration-rule-strong">The law</summary>
                <div className="pt-2">
                  <Quote rule={item.rule} />
                </div>
              </details>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function PlaceBlock({ place, today }: { place: Place; today: string }) {
  return (
    <article aria-labelledby={`place-${place.code}`} className="space-y-5 border-t-2 border-ink pt-5">
      <header className="flex flex-wrap items-baseline gap-x-3">
        <h2 id={`place-${place.code}`} className="text-[28px] font-medium tracking-[-0.03em]">
          {place.name}
        </h2>
        <span className="font-mono text-[13px] text-ink-soft">{place.code}</span>
      </header>
      {place.law_changed.length > 0 ? (
        <p className="notch bg-signal-soft px-3 py-2 text-[14px] text-signal-ink">
          The law behind {place.law_changed.length} live rule source
          {place.law_changed.length > 1 ? "s" : ""} read differently at the monthly check:{" "}
          {place.law_changed.map((item) => hostOf(item.url)).join(", ")}.
        </p>
      ) : null}
      <div className="grid items-start gap-8 lg:grid-cols-[minmax(0,1fr)_24rem]">
        <div className="space-y-8">
          {place.page ? <PageSection code={place.code} page={place.page} /> : null}
          <RuleChanges code={place.code} items={place.rule_changes} />
        </div>
        <DatesAhead place={place} today={today} />
      </div>
    </article>
  );
}

type State = { code: string; name: string };

export function ChangesApp() {
  const [heldStates, setHeldStates] = useState<State[]>([]);
  const [states, setStates] = useState<string[] | null>(null);
  const [care, setCare] = useState("behavioral_health");
  const [data, setData] = useState<Changes | null>(null);
  const [error, setError] = useState<string | null>(null);
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let live = true;
    fetch("/api/options")
      .then(async (response) => {
        const body = await response.json();
        if (!live) return;
        if (!response.ok) throw new Error(body.error ?? "The states could not be loaded.");
        const held: State[] = body.patient_states;
        setHeldStates(held);
        setStates(held.map((state) => state.code));
      })
      .catch((problem: Error) => live && setError(problem.message));
    return () => {
      live = false;
    };
  }, []);

  useEffect(() => {
    if (states === null) return;
    const query = new URLSearchParams({ states: states.join(","), care });
    let live = true;
    fetch(`/api/changes?${query}`)
      .then(async (response) => {
        const body = await response.json();
        if (!live) return;
        if (!response.ok) throw new Error(body.error ?? "The changes could not be loaded.");
        setData(body);
        setError(null);
      })
      .catch((problem: Error) => live && setError(problem.message));
    return () => {
      live = false;
    };
  }, [states, care]);

  useEffect(() => {
    if (!data || !root.current) return;
    const scope = createScope({
      root: root.current,
      mediaQueries: { reduceMotion: "(prefers-reduced-motion: reduce)" },
    }).add((self) => {
      if (self?.matches.reduceMotion) return;
      animate("[data-row]", {
        opacity: [0, 1],
        y: [6, 0],
        duration: 320,
        ease: "out(3)",
        delay: stagger(30),
      });
    });
    return () => scope.revert();
  }, [data]);

  function toggle(code: string) {
    setStates((now) =>
      now === null ? [code] : now.includes(code) ? now.filter((item) => item !== code) : [...now, code],
    );
  }

  return (
    <div ref={root} className="space-y-10">
      <form
        aria-label="Choose what to watch"
        className="flex flex-wrap items-end gap-x-8 gap-y-4 border border-rule bg-sheet p-4"
        onSubmit={(event) => event.preventDefault()}
      >
        <fieldset className="space-y-2">
          <legend className="text-[13px] font-semibold tracking-wide text-ink-soft uppercase">
            States you serve
          </legend>
          <div className="flex flex-wrap gap-2">
            {heldStates.map((state) => (
              <label
                key={state.code}
                className="press flex min-h-11 cursor-pointer items-center gap-2 border border-rule-strong px-3 text-[15px] has-checked:border-ink has-checked:bg-ink has-checked:text-white"
              >
                <input
                  type="checkbox"
                  className="size-4 accent-signal"
                  checked={states?.includes(state.code) ?? false}
                  onChange={() => toggle(state.code)}
                />
                {state.name}
              </label>
            ))}
          </div>
        </fieldset>
        <fieldset className="space-y-2">
          <legend className="text-[13px] font-semibold tracking-wide text-ink-soft uppercase">
            Line of care
          </legend>
          <div className="flex flex-wrap gap-2">
            {CARE.map((option) => (
              <label
                key={option.value}
                className="press flex min-h-11 cursor-pointer items-center gap-2 border border-rule-strong px-3 text-[15px] has-checked:border-ink has-checked:bg-ink has-checked:text-white"
              >
                <input
                  type="radio"
                  name="care"
                  className="size-4 accent-signal"
                  value={option.value}
                  checked={care === option.value}
                  onChange={() => setCare(option.value)}
                />
                {option.label}
              </label>
            ))}
          </div>
        </fieldset>
        <p className="max-w-[38ch] text-[13px] text-ink-soft">
          Medicare rules are federal, so they are always listed. More states will be added as their law is
          read.
        </p>
      </form>

      {error ? (
        <p role="alert" className="border border-stop bg-stop-soft px-4 py-3 text-[15px] text-stop">
          {error}
        </p>
      ) : null}
      {!data && !error ? (
        <p role="status" className="text-[15px] text-ink-soft">
          Loading what changed…
        </p>
      ) : null}
      {data ? (
        <div className="space-y-12" aria-live="polite">
          <p className="text-[14px] text-ink-soft">
            As of <span className="font-mono text-ink">{formatDate(data.today)}</span>. Dates shown from{" "}
            <span className="font-mono">{formatDate(data.window.from)}</span> to{" "}
            <span className="font-mono">{formatDate(data.window.to)}</span>. {data.notice.not_legal_advice}
          </p>
          {data.places.map((place) => (
            <PlaceBlock key={place.code} place={place} today={data.today} />
          ))}
        </div>
      ) : null}
    </div>
  );
}
