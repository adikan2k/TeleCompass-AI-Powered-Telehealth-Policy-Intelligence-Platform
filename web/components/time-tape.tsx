"use client";

import Counter from "@/components/vendor/Counter";
import { Compass } from "@/components/compass";
import { formatDate, monthName, yearOf } from "@/lib/format";

// The tape runs month by month over three years. Each month turns the compass by 10 degrees.
export const FIRST_YEAR = 2026;
export const MONTHS = 36;

export type Mark = { date: string; count: number };

export function indexOf(iso: string): number {
  const [year, month] = iso.split("-").map(Number);
  return Math.min(Math.max((year - FIRST_YEAR) * 12 + (month - 1), 0), MONTHS - 1);
}

export function dateOf(index: number): string {
  const year = FIRST_YEAR + Math.floor(index / 12);
  return `${year}-${String((index % 12) + 1).padStart(2, "0")}-01`;
}

// Where month `index` sits on the scale, matching the centre of the 14px thumb.
function position(index: number): string {
  return `calc(7px + (100% - 14px) * ${index / (MONTHS - 1)})`;
}

export function TimeTape({
  value,
  marks,
  onChange,
}: {
  value: string;
  marks: Mark[];
  onChange: (iso: string) => void;
}) {
  const index = indexOf(value);
  const markIndexes = marks.map((mark) => ({ ...mark, index: indexOf(mark.date) }));
  const before = markIndexes.filter((mark) => mark.date < value).at(-1);
  const after = markIndexes.find((mark) => mark.date > value);

  return (
    <div className="border border-rule bg-sheet">
      <div className="grid grid-cols-[5.5rem_minmax(0,1fr)] items-center gap-4 px-4 pt-4 sm:grid-cols-[7rem_minmax(0,1fr)] sm:px-5">
        <Compass heading={index * 10} className="aspect-square w-full" />
        <div className="min-w-0">
          <p className="text-[13px] text-ink-soft">Checking the visit for</p>
          <p className="flex flex-wrap items-baseline gap-x-2 text-[34px] leading-none font-medium tracking-[-0.03em] sm:text-[40px]">
            <span>{monthName(value)}</span>
            <Counter
              value={yearOf(value)}
              format={{ useGrouping: false }}
              fontSize="1em"
              fontWeight={500}
              intro={false}
              duration={0.5}
              bounce={0}
              stagger={0.03}
            />
          </p>
          <p className="mt-2 font-mono text-[13px] text-ink-soft">
            {value === dateOf(index) ? `From ${formatDate(value)}` : formatDate(value)}
          </p>
        </div>
      </div>

      <div className="px-4 pt-5 pb-4 sm:px-5">
        <div className="tape relative">
          {/* The drawn scale. Purely visual: the range input below carries the meaning. */}
          <div className="pointer-events-none absolute inset-x-0 top-0 h-11" aria-hidden="true">
            <div className="absolute inset-x-[7px] top-1/2 h-px bg-rule-strong" />
            {Array.from({ length: MONTHS }, (_, i) => (
              <span
                key={i}
                className={`absolute top-1/2 w-px -translate-x-1/2 ${i % 12 === 0 ? "h-5 -translate-y-1/2 bg-ink" : "h-2.5 -translate-y-1/2 bg-rule-strong"}`}
                style={{ left: position(i) }}
              />
            ))}
            {markIndexes.map((mark) => (
              <span
                key={mark.date}
                className="absolute top-0 h-11 w-0.5 -translate-x-1/2 bg-signal"
                style={{ left: position(mark.index) }}
              />
            ))}
          </div>
          <input
            type="range"
            className="tape-input relative"
            min={0}
            max={MONTHS - 1}
            step={1}
            value={index}
            onChange={(event) => onChange(dateOf(Number(event.target.value)))}
            aria-label="Date of the visit"
            aria-valuetext={`${monthName(value)} ${yearOf(value)}`}
          />
          <div className="relative mt-1 h-5 text-[13px] text-ink-soft" aria-hidden="true">
            {[0, 12, 24].map((i) => (
              <span key={i} className="absolute -translate-x-[7px] font-mono" style={{ left: position(i) }}>
                {FIRST_YEAR + i / 12}
              </span>
            ))}
          </div>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-3 border-t border-rule pt-3">
          {marks.length > 0 ? (
            <p className="w-full text-[14px] text-ink-soft sm:w-auto sm:flex-1">
              <span aria-hidden="true" className="mr-2 inline-block h-3 w-0.5 bg-signal align-[-1px]" />
              {marks.length === 1 ? "One date" : `${marks.length} dates`} where a rule we hold starts or
              ends:{" "}
              {marks.map((mark, i) => (
                <span key={mark.date}>
                  {i > 0 ? ", " : ""}
                  <span className="font-mono text-ink">{formatDate(mark.date)}</span> ({mark.count}{" "}
                  {mark.count === 1 ? "rule" : "rules"})
                </span>
              ))}
              .
            </p>
          ) : (
            <p className="w-full text-[14px] text-ink-soft sm:w-auto sm:flex-1">No rule in this answer carries a date.</p>
          )}
          <div className="flex gap-2">
            <button
              type="button"
              disabled={!before}
              onClick={() => before && onChange(before.date)}
              className="press min-h-11 border border-rule-strong bg-sheet px-3 text-[14px] font-medium hover:border-ink disabled:opacity-45"
            >
              Previous change
            </button>
            <button
              type="button"
              disabled={!after}
              onClick={() => after && onChange(after.date)}
              className="press min-h-11 border border-rule-strong bg-sheet px-3 text-[14px] font-medium hover:border-ink disabled:opacity-45"
            >
              Next change
            </button>
          </div>
          <label className="flex items-center gap-2 text-[14px]">
            <span className="text-ink-soft">Exact date</span>
            <input
              type="date"
              value={value}
              min={`${FIRST_YEAR}-01-01`}
              max={`${FIRST_YEAR + MONTHS / 12 - 1}-12-31`}
              onChange={(event) => event.target.value && onChange(event.target.value)}
              className="min-h-11 border border-rule-strong bg-sheet px-2 font-mono text-[14px]"
            />
          </label>
        </div>
      </div>
    </div>
  );
}
