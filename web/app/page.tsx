import { PreflightForm } from "@/components/preflight-form";

export default function Home() {
  return (
    <div className="space-y-6">
      <div className="max-w-3xl space-y-2">
        <h1 className="text-3xl font-semibold tracking-tight">
          Is this telehealth visit allowed, and will it be paid?
        </h1>
        <p className="text-base text-muted-foreground">
          Describe the visit and pick a date. Each answer comes with the exact words of the law
          behind it. Where the law we hold says nothing, the answer says so.
        </p>
      </div>
      <PreflightForm />
      <section className="max-w-3xl space-y-2 border-t border-border pt-6 text-sm">
        <h2 className="text-lg font-semibold">How the answers are made</h2>
        <ol className="list-decimal space-y-1 pl-5">
          <li>
            The statutes, rules and manuals a state’s policy index cites are fetched and stored.
          </li>
          <li>A model reads them into rules. Each rule must carry a quote from the law.</li>
          <li>
            Code checks that every quote appears word for word in the stored law. A rule that
            fails is not used.
          </li>
          <li>A second model reviews each rule against the law.</li>
          <li>
            Plain code, not a model, applies the rules to your visit. The same visit always gets
            the same answer.
          </li>
        </ol>
        <p className="text-muted-foreground">
          No person has reviewed the rules yet. Each rule shows how it was checked.
        </p>
      </section>
    </div>
  );
}
