import type { Decision, Evidence, Line, Verdict } from "@/lib/api";

// How each verdict looks. Every verdict has its own word, symbol and border style, so it can
// be told apart without colour.
const VERDICTS: Record<Verdict, { word: string; symbol: string; box: string; chip: string }> = {
  allowed: {
    word: "Allowed",
    symbol: "✓",
    box: "border-l-ok border-l-4 border-solid",
    chip: "bg-ok-soft text-ok border-ok border-solid",
  },
  allowed_with_conditions: {
    word: "Allowed with conditions",
    symbol: "◐",
    box: "border-l-warn border-l-4 border-dashed",
    chip: "bg-warn-soft text-warn border-warn border-dashed",
  },
  not_allowed: {
    word: "Not allowed",
    symbol: "✕",
    box: "border-l-stop border-l-8 border-double",
    chip: "bg-stop-soft text-stop border-stop border-double border-4",
  },
  silent: {
    word: "Silent: we hold no rule on this",
    symbol: "○",
    box: "border-l-quiet border-l-4 border-dotted",
    chip: "bg-quiet-soft text-quiet border-quiet border-dotted",
  },
  not_applicable: {
    word: "Does not apply",
    symbol: "–",
    box: "border-l-border border-l-4 border-solid",
    chip: "bg-card text-muted-foreground border-border border-solid",
  },
};

const REFERENCE_NOTE = " (for reference: the payer is not Medicare)";

function reviewText(verdict: string | null): string {
  if (verdict === "right") return "passed";
  if (verdict === "wrong") return "flagged for a closer look";
  if (verdict === "cannot_tell") return "could not decide";
  return "not reviewed";
}

function RuleCard({ rule }: { rule: Evidence }) {
  const dated = rule.effective_from || rule.effective_to;
  return (
    <li className="rounded-md border border-border bg-background p-3">
      <p className="text-sm font-medium">{rule.summary}</p>
      {dated ? (
        <p className="mt-1 text-xs text-muted-foreground">
          In force {rule.effective_from ?? "from an unstated date"} to{" "}
          {rule.effective_to ?? "no stated end"}.
        </p>
      ) : null}
      <blockquote className="mt-2 border-l-2 border-primary pl-3 font-mono text-xs leading-relaxed text-foreground">
        “{rule.quote}”
      </blockquote>
      <p className="mt-2 text-xs text-muted-foreground">
        {rule.source_url ? (
          <a
            href={rule.source_url}
            target="_blank"
            rel="noreferrer"
            className="break-all font-medium text-primary underline underline-offset-2"
          >
            Read it at the source
          </a>
        ) : (
          "No source link"
        )}
        {rule.source_fetched ? `, fetched ${rule.source_fetched}.` : "."}
      </p>
      <p className="mt-1 text-xs text-muted-foreground">
        Quote found word for word in the source: yes. Second-model review:{" "}
        {reviewText(rule.auto_review)}. Reviewed by a person:{" "}
        {rule.status === "approved" ? "yes" : "not yet"}.
      </p>
    </li>
  );
}

function RuleGroup({ heading, rules }: { heading: string; rules: Evidence[] }) {
  if (rules.length === 0) return null;
  return (
    <section className="mt-3">
      <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {heading}
      </h4>
      <ul className="mt-2 space-y-2">
        {rules.map((rule) => (
          <RuleCard key={rule.rule_id} rule={rule} />
        ))}
      </ul>
    </section>
  );
}

function LineCard({ line }: { line: Line }) {
  const look = VERDICTS[line.verdict];
  const count = line.evidence.length + line.conditions.length + line.would_allow.length;
  return (
    <article className={`rounded-lg border border-border bg-card p-4 ${look.box}`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <h3 className="text-base font-semibold">{line.title.replace(REFERENCE_NOTE, "")}</h3>
        <span
          className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-sm font-semibold ${look.chip}`}
        >
          <span aria-hidden="true">{look.symbol}</span>
          {look.word}
        </span>
      </div>
      <p className="mt-2 text-sm">{line.reason}</p>
      {count > 0 ? (
        <details className="mt-3">
          <summary className="cursor-pointer text-sm font-medium text-primary underline underline-offset-2">
            Show the law behind this ({count} {count === 1 ? "rule" : "rules"})
          </summary>
          <RuleGroup heading="Based on" rules={line.evidence} />
          <RuleGroup heading="Conditions" rules={line.conditions} />
          <RuleGroup heading="Would be allowed if" rules={line.would_allow} />
        </details>
      ) : null}
    </article>
  );
}

export function DecisionView({ decision }: { decision: Decision }) {
  const state = decision.lines.filter((line) => !line.key.startsWith("medicare_"));
  const medicare = decision.lines.filter((line) => line.key.startsWith("medicare_"));
  const forReference = medicare.some((line) => line.title.includes(REFERENCE_NOTE));
  return (
    <div className="space-y-6">
      <p className="rounded-md bg-secondary p-3 text-sm">
        <span className="font-semibold">The visit: </span>
        {decision.summary}
      </p>
      <section aria-label="State rules" className="space-y-3">
        <h2 className="text-lg font-semibold">State rules</h2>
        {state.map((line) => (
          <LineCard key={line.key} line={line} />
        ))}
      </section>
      {medicare.length > 0 ? (
        <section aria-label="Federal Medicare rules" className="space-y-3">
          <h2 className="text-lg font-semibold">Federal Medicare rules</h2>
          <p className="text-sm text-muted-foreground">
            These have start and end dates, so they change when you move the date.
            {forReference ? " Shown for reference, because the payer here is not Medicare." : ""}
          </p>
          {medicare.map((line) => (
            <LineCard key={line.key} line={line} />
          ))}
        </section>
      ) : null}
      <p className="text-xs text-muted-foreground">
        State rules are shown as fetched. A rule with no stated start date is treated as in force
        on any date, so only dated rules change when the date changes.{" "}
        {decision.notice.not_legal_advice} Sources last fetched{" "}
        {decision.notice.sources_last_fetched}.
      </p>
    </div>
  );
}
