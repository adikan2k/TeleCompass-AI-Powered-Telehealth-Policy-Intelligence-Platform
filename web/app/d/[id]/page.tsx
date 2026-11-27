import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";

import { DecisionView } from "@/components/decision-view";
import { apiUrl, type Decision } from "@/lib/api";

// A stored answer, shown exactly as it was given. The same request is made for the page and
// for its link preview; Next.js makes it once.
async function getDecision(id: string): Promise<Decision> {
  const response = await fetch(`${apiUrl()}/decisions/${encodeURIComponent(id)}`);
  if (response.status === 404) notFound();
  if (!response.ok) throw new Error(`The answer could not be loaded (${response.status}).`);
  return response.json();
}

export async function generateMetadata({ params }: PageProps<"/d/[id]">): Promise<Metadata> {
  const { id } = await params;
  const decision = await getDecision(id);
  const description = `${decision.summary}. Each answer shows the words of the law behind it.`;
  return {
    title: "A stored preflight answer",
    description,
    openGraph: { title: "TeleCompass: a stored preflight answer", description },
  };
}

async function Stored({ params }: Pick<PageProps<"/d/[id]">, "params">) {
  const { id } = await params;
  const decision = await getDecision(id);
  const when = decision.created_at ? decision.created_at.slice(0, 10) : null;
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        {when ? `Answered on ${when}. ` : ""}This page shows the answer exactly as it was given,
        with the rules it rested on then.
      </p>
      <DecisionView decision={decision} />
    </div>
  );
}

export default function Page({ params }: PageProps<"/d/[id]">) {
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h1 className="text-3xl font-semibold tracking-tight">A stored preflight answer</h1>
        <Link href="/" className="text-sm font-medium text-primary underline underline-offset-2">
          Check a visit of your own
        </Link>
      </div>
      <Suspense fallback={<p className="text-sm text-muted-foreground">Loading the answer…</p>}>
        <Stored params={params} />
      </Suspense>
    </div>
  );
}
