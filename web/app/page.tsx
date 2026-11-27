import { PreflightApp } from "@/components/preflight-app";

const STEPS = [
  {
    title: "Fetch the law itself",
    text: "A state’s policy index names the statutes, rules and manuals it relies on. Those are fetched, where the site allows it, and stored with the date.",
  },
  {
    title: "Read it into rules",
    text: "A model reads the stored law into rules. Every rule must carry a quote from the law.",
  },
  {
    title: "Check every quote",
    text: "Code looks for each quote, word for word, in the stored text. A rule whose quote is not there is never used.",
  },
  {
    title: "Review each rule",
    text: "A second model checks each rule against the law. Then a person approves or rejects it; only approved rules are used here, and each rule shows how it was checked.",
  },
  {
    title: "Decide with plain code",
    text: "Ordinary code, not a model, applies the rules to the visit and the date. The same visit always gets the same answer.",
  },
];

export default function Home() {
  return (
    <div className="space-y-12">
      <div className="max-w-[62rem] space-y-4">
        <h1 className="max-w-[22ch] text-[40px] leading-[1.02] font-medium tracking-[-0.035em] sm:text-[54px]">
          Is this telehealth visit allowed, and will it be paid?
        </h1>
        <p className="max-w-[60ch] text-[17px] text-ink-soft">
          Describe the visit and pick a date. Each line of the answer opens to the exact words of the
          law behind it. Where the law we hold says nothing, the answer says so.
        </p>
      </div>

      <PreflightApp />

      <section id="how" aria-labelledby="how-heading" className="scroll-mt-6 border-t border-rule pt-10">
        <div className="grid gap-8 lg:grid-cols-[21rem_minmax(0,1fr)] lg:gap-8">
          <div>
            <h2 id="how-heading" className="text-[28px] leading-tight font-medium tracking-[-0.025em]">
              How an answer is made
            </h2>
            <p className="mt-2 text-[15px] text-ink-soft">
              The model reads; it never decides. Each step leaves a record that can be checked.
            </p>
          </div>
          <ol className="relative space-y-6 border-l border-rule-strong pl-6">
            {STEPS.map((step) => (
              <li key={step.title} className="relative">
                <span
                  aria-hidden="true"
                  className="absolute top-[0.45em] -left-[29px] size-2.5 rotate-45 border-2 border-ink bg-paper"
                />
                <h3 className="text-[17px] font-semibold">{step.title}</h3>
                <p className="mt-1 max-w-[62ch] text-[15px] text-ink-soft">{step.text}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>
    </div>
  );
}
