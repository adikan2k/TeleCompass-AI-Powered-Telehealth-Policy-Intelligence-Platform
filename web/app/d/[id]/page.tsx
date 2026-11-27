import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";

import { Checklist } from "@/components/checklist";
import { apiUrl, type Decision } from "@/lib/api";
import { formatDate, readable } from "@/lib/format";

// A stored answer, shown exactly as it was given. The page and its link preview make the
// same request; Next.js makes it once.
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
  return (
    <div className="grid items-start gap-6 lg:grid-cols-[21rem_minmax(0,1fr)] lg:gap-8">
      <aside className="space-y-4 border border-rule bg-sheet p-5 lg:sticky lg:top-4">
        <h2 className="text-[20px] font-semibold">The visit</h2>
        <p className="text-[15px]">{readable(decision.summary)}.</p>
        <dl className="grid grid-cols-[max-content_minmax(0,1fr)] gap-x-4 gap-y-1 border-t border-rule pt-3 text-[14px]">
          <dt className="text-ink-soft">Answered</dt>
          <dd className="font-mono">{formatDate(decision.created_at)}</dd>
          <dt className="text-ink-soft">Link</dt>
          <dd className="font-mono [overflow-wrap:anywhere]">/d/{decision.id}</dd>
        </dl>
        <p className="text-[14px] text-ink-soft">
          This page keeps the answer exactly as it was given, with the rules it rested on then, even if
          the rules change later.
        </p>
      </aside>
      <Checklist decision={decision} runKey="stored" />
    </div>
  );
}

export default function Page({ params }: PageProps<"/d/[id]">) {
  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <h1 className="text-[40px] leading-[1.02] font-medium tracking-[-0.035em] sm:text-[48px]">
          A stored answer
        </h1>
        <Link
          href="/"
          className="press notch inline-flex min-h-11 items-center bg-ink px-4 text-[15px] font-semibold text-white"
        >
          Check a visit of your own
        </Link>
      </div>
      <Suspense
        fallback={
          <p role="status" className="text-[15px] text-ink-soft">
            Loading the stored answer…
          </p>
        }
      >
        <Stored params={params} />
      </Suspense>
    </div>
  );
}
