"use client";

import { animate, createScope, stagger, svg } from "animejs";
import { useEffect, useId, useRef, useState } from "react";

import { VERDICTS, VerdictGlyph, VerdictTag } from "@/components/verdict";
import type { Decision, Evidence, Line, Verdict } from "@/lib/api";
import { formatDate, hostOf, readable } from "@/lib/format";

export type Change = { from: Verdict; when: string };

const STATE_NAMES: Record<string, string> = { FL: "Florida" };
const REFERENCE_NOTE = " (for reference: the payer is not Medicare)";

function reviewWords(verdict: string | null): string {
  if (verdict === "right") return "passed";
  if (verdict === "wrong") return "flagged it for a closer look";
  if (verdict === "cannot_tell") return "could not decide";
  return "not run";
}

function RuleEntry({ rule }: { rule: Evidence }) {
  const dated = rule.effective_from || rule.effective_to;
  return (
    <li className="py-4 first:pt-1">
      <figure className="space-y-3">
        <p className="max-w-[68ch] font-medium">{rule.summary}</p>
        <blockquote
          cite={rule.source_url ?? undefined}
          className="law-quote max-w-[68ch] border border-rule bg-quote px-4 py-3 text-[16px] leading-[1.65]"
        >
          {rule.quote}
        </blockquote>
        <figcaption>
          <dl className="grid grid-cols-[max-content_minmax(0,1fr)] gap-x-4 gap-y-1 text-[13px]">
            <dt className="text-ink-soft">Source</dt>
            <dd className="min-w-0">
              {rule.source_url ? (
                <a
                  href={rule.source_url}
                  target="_blank"
                  rel="noreferrer"
                  className="font-medium underline [overflow-wrap:anywhere]"
                >
                  {hostOf(rule.source_url)}
                </a>
              ) : (
                "No link stored"
              )}
              {rule.source_fetched ? (
                <span className="text-ink-soft">
                  , fetched <span className="font-mono">{formatDate(rule.source_fetched)}</span>
                </span>
              ) : null}
            </dd>
            {dated ? (
              <>
                <dt className="text-ink-soft">In force</dt>
                <dd className="font-mono">
                  {rule.effective_from ? formatDate(rule.effective_from) : "no stated start"}
                  {" to "}
                  {rule.effective_to ? formatDate(rule.effective_to) : "no stated end"}
                </dd>
              </>
            ) : null}
            <dt className="text-ink-soft">Checked</dt>
            <dd>
              Quote found word for word in the source. Second model {reviewWords(rule.auto_review)}.{" "}
              {rule.status === "approved" ? "Approved by a person." : "Not yet reviewed by a person."}
            </dd>
          </dl>
        </figcaption>
      </figure>
    </li>
  );
}

function RuleGroup({ heading, rules }: { heading: string; rules: Evidence[] }) {
  if (rules.length === 0) return null;
  return (
    <section className="mt-4 first:mt-0">
      <h4 className="text-[13px] font-semibold text-ink-soft">{heading}</h4>
      <ul className="divide-y divide-rule">
        {rules.map((rule) => (
          <RuleEntry key={rule.rule_id} rule={rule} />
        ))}
      </ul>
    </section>
  );
}

function Row({
  line,
  open,
  onToggle,
  change,
  animateIn,
}: {
  line: Line;
  open: boolean;
  onToggle: () => void;
  change?: Change;
  animateIn: boolean;
}) {
  const regionId = useId();
  const look = VERDICTS[line.verdict];
  const count = line.evidence.length + line.conditions.length + line.would_allow.length;
  return (
    <li
      className="grid grid-cols-[2rem_minmax(0,1fr)] gap-x-3 px-4 py-4 sm:px-5"
      data-changed={change ? "true" : undefined}
      data-animate={animateIn ? "true" : undefined}
    >
      <span className={`pt-0.5 ${look.text}`}>
        <VerdictGlyph verdict={line.verdict} size={26} />
      </span>
      <div className="min-w-0" data-row-body>
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h3 className="text-[17px] font-semibold tracking-[-0.01em]">
            {line.title.replace(REFERENCE_NOTE, "")}
          </h3>
          <span className="leader hidden sm:block" aria-hidden="true" />
          <VerdictTag verdict={line.verdict} />
        </div>
        <p className="mt-1 max-w-[70ch] text-[15px] text-ink-soft">{readable(line.reason)}</p>
        {change ? (
          <p className="mt-2 flex items-center gap-2 text-[14px] font-medium text-signal-ink">
            <span aria-hidden="true" className="inline-block size-2 rotate-45 bg-signal" />
            Changed. For {change.when} this line read: {VERDICTS[change.from].word}.
          </p>
        ) : null}
        {count > 0 ? (
          <>
            <button
              type="button"
              onClick={onToggle}
              aria-expanded={open}
              aria-controls={regionId}
              className="press mt-2 -ml-1 inline-flex min-h-11 items-center gap-2 px-1 text-[15px] font-medium underline decoration-rule-strong underline-offset-4 hover:decoration-ink"
            >
              <svg
                viewBox="0 0 16 16"
                className={`size-3.5 transition-transform duration-200 ease-[var(--ease-out)] motion-reduce:transition-none ${open ? "rotate-90" : ""}`}
                aria-hidden="true"
              >
                <path d="M6 3l5 5-5 5" fill="none" stroke="currentColor" strokeWidth="2" />
              </svg>
              {open ? "Hide the law" : "Show the law"} ({count} {count === 1 ? "rule" : "rules"})
            </button>
            <div
              id={regionId}
              role="region"
              aria-label={`The law behind: ${line.title.replace(REFERENCE_NOTE, "")}`}
              className="disclose"
              data-open={open ? "true" : "false"}
              inert={!open}
            >
              <div>
                <div className="pt-2 pb-1">
                  <RuleGroup heading="Based on" rules={line.evidence} />
                  <RuleGroup heading="Conditions" rules={line.conditions} />
                  <RuleGroup heading="Would be allowed if" rules={line.would_allow} />
                </div>
              </div>
            </div>
          </>
        ) : null}
      </div>
    </li>
  );
}

function stateNameOf(decision: Decision): string {
  const match = /patient in ([A-Z]{2})/.exec(decision.summary);
  return match ? (STATE_NAMES[match[1]] ?? match[1]) : "the patient's state";
}

export function Checklist({
  decision,
  runKey,
  changes = {},
  firstRun = false,
  busy = false,
  startOpen = [],
}: {
  decision: Decision;
  runKey: string;
  changes?: Record<string, Change>;
  firstRun?: boolean;
  busy?: boolean;
  startOpen?: string[];
}) {
  const [open, setOpen] = useState<Set<string>>(() => new Set(startOpen));
  const root = useRef<HTMLDivElement>(null);
  const state = decision.lines.filter((line) => !line.key.startsWith("medicare_"));
  const medicare = decision.lines.filter((line) => line.key.startsWith("medicare_"));
  const expandable = decision.lines.filter(
    (line) => line.evidence.length + line.conditions.length + line.would_allow.length > 0,
  );
  const allOpen = expandable.length > 0 && expandable.every((line) => open.has(line.key));
  const forReference = medicare.some((line) => line.title.includes(REFERENCE_NOTE));

  // Motion has one job here: show what just changed. On a first answer the glyphs draw in,
  // quickly and only for the first few lines. On a re-run only the lines that changed move.
  useEffect(() => {
    const scope = createScope({
      root,
      mediaQueries: { reduceMotion: "(prefers-reduced-motion: reduce)" },
    }).add((self) => {
      if (self?.matches.reduceMotion) return;
      animate(svg.createDrawable('[data-animate="true"] [data-draw]'), {
        draw: ["0 0", "0 1"],
        duration: 240,
        delay: stagger(38, { ease: "out(2)" }),
        ease: "out(3)",
      });
      animate('[data-changed="true"] [data-row-body]', {
        opacity: [0.35, 1],
        filter: ["blur(2px)", "blur(0px)"],
        duration: 200,
        ease: "out(3)",
      });
    });
    return () => scope.revert();
  }, [runKey]);

  function toggle(key: string) {
    setOpen((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function toggleAll() {
    setOpen(allOpen ? new Set() : new Set(expandable.map((line) => line.key)));
  }

  const animatedKeys = new Set(
    firstRun ? decision.lines.slice(0, 6).map((line) => line.key) : Object.keys(changes),
  );

  const renderRows = (lines: Line[]) =>
    lines.map((line) => (
      <Row
        key={line.key}
        line={line}
        open={open.has(line.key)}
        onToggle={() => toggle(line.key)}
        change={changes[line.key]}
        animateIn={animatedKeys.has(line.key)}
      />
    ));

  return (
    <div ref={root} className="space-y-6" aria-busy={busy}>
      {expandable.length > 0 ? (
        <div className="flex justify-end">
          <button
            type="button"
            onClick={toggleAll}
            className="press min-h-11 px-1 text-[14px] font-medium underline decoration-rule-strong underline-offset-4 hover:decoration-ink"
          >
            {allOpen ? "Hide all the law" : "Show all the law"}
          </button>
        </div>
      ) : null}
      <section aria-labelledby="state-rules" className="border border-rule bg-sheet">
        <header className="flex flex-wrap items-baseline justify-between gap-2 border-b border-rule px-4 py-3 sm:px-5">
          <h2 id="state-rules" className="text-[20px] font-semibold">
            {stateNameOf(decision)} law
          </h2>
          <p className="text-[13px] text-ink-soft">Shown as fetched; most state rules carry no start date.</p>
        </header>
        <ol className={`divide-y divide-rule transition-opacity duration-150 ${busy ? "opacity-60" : ""}`}>
          {renderRows(state)}
        </ol>
      </section>
      {medicare.length > 0 ? (
        <section aria-labelledby="federal-rules" className="border border-rule bg-sheet">
          <header className="flex flex-wrap items-baseline justify-between gap-2 border-b border-rule px-4 py-3 sm:px-5">
            <h2 id="federal-rules" className="text-[20px] font-semibold">
              Federal Medicare
            </h2>
            <p className="text-[13px] text-ink-soft">
              Dated rules: these move with the date.
              {forReference ? " Shown for reference; the payer here is not Medicare." : ""}
            </p>
          </header>
          <ol className={`divide-y divide-rule transition-opacity duration-150 ${busy ? "opacity-60" : ""}`}>
            {renderRows(medicare)}
          </ol>
        </section>
      ) : null}
      <p className="max-w-[70ch] text-[13px] text-ink-soft">
        {decision.notice.not_legal_advice} Sources last fetched{" "}
        <span className="font-mono">{formatDate(decision.notice.sources_last_fetched)}</span>. A
        rule with no stated start date is treated as in force on any date, so only dated rules
        change when the date changes.
      </p>
    </div>
  );
}
