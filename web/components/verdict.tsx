import type { Verdict } from "@/lib/api";

// Each verdict has three cues: a glyph shape, a word, and a colour. The shapes are told apart
// without colour: a ring with a tick, a dashed ring with a tick, an octagon with a cross,
// an empty dotted ring, and a bare dash.
export const VERDICTS: Record<
  Verdict,
  { word: string; short: string; text: string; tint: string; border: string }
> = {
  allowed: {
    word: "Allowed",
    short: "Allowed",
    text: "text-ok",
    tint: "bg-ok-soft",
    border: "border-ok",
  },
  allowed_with_conditions: {
    word: "Allowed with conditions",
    short: "With conditions",
    text: "text-warn",
    tint: "bg-warn-soft",
    border: "border-warn",
  },
  not_allowed: {
    word: "Not allowed",
    short: "Not allowed",
    text: "text-stop",
    tint: "bg-stop-soft",
    border: "border-stop",
  },
  silent: {
    word: "Silent: no rule found",
    short: "Silent",
    text: "text-quiet",
    tint: "bg-quiet-soft",
    border: "border-quiet",
  },
  not_applicable: {
    word: "Does not apply",
    short: "Does not apply",
    text: "text-ink-soft",
    tint: "bg-paper",
    border: "border-rule-strong",
  },
};

const RING = "M12 3a9 9 0 1 1 0 18a9 9 0 1 1 0-18";
const OCTAGON = "M8.3 3h7.4L21 8.3v7.4L15.7 21H8.3L3 15.7V8.3z";

/** The verdict's glyph. Inner marks carry `data-draw` so they can be drawn in on change. */
export function VerdictGlyph({ verdict, size = 22 }: { verdict: Verdict; size?: number }) {
  const common = {
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
  };
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} aria-hidden="true" className="shrink-0">
      {verdict === "allowed" ? (
        <>
          <path d={RING} {...common} />
          <path data-draw d="M7.6 12.4l3 3 5.8-6.6" {...common} strokeWidth={2.4} />
        </>
      ) : null}
      {verdict === "allowed_with_conditions" ? (
        <>
          <path d={RING} {...common} strokeDasharray="3.2 2.6" />
          <path data-draw d="M7.6 12.4l3 3 5.8-6.6" {...common} strokeWidth={2.4} />
        </>
      ) : null}
      {verdict === "not_allowed" ? (
        <>
          <path d={OCTAGON} {...common} />
          <path data-draw d="M9 9l6 6M15 9l-6 6" {...common} strokeWidth={2.4} />
        </>
      ) : null}
      {verdict === "silent" ? <path d={RING} {...common} strokeDasharray="0.1 3.3" /> : null}
      {verdict === "not_applicable" ? <path data-draw d="M7 12h10" {...common} /> : null}
    </svg>
  );
}

/** The verdict as a tag: glyph, word and tint, in the site's notched shape. */
export function VerdictTag({ verdict, compact = false }: { verdict: Verdict; compact?: boolean }) {
  const look = VERDICTS[verdict];
  return (
    <span
      className={`notch inline-flex items-center gap-1.5 py-1 pr-3 pl-1.5 text-sm font-medium ${look.tint} ${look.text}`}
    >
      <VerdictGlyph verdict={verdict} size={18} />
      {compact ? look.short : look.word}
    </span>
  );
}
