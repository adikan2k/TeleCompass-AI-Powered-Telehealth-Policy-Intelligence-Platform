import type { Metadata } from "next";
import { Fragment_Mono, Schibsted_Grotesk } from "next/font/google";
import Link from "next/link";
import { connection } from "next/server";
import { Suspense } from "react";

import { apiUrl } from "@/lib/api";
import { formatDate } from "@/lib/format";

import "./globals.css";

// One grotesque for every sentence; a mono only for dates, links and codes.
const schibsted = Schibsted_Grotesk({ variable: "--font-schibsted", subsets: ["latin"] });
const fragment = Fragment_Mono({ variable: "--font-fragment", subsets: ["latin"], weight: "400" });

// Where the site lives, for link previews. Vercel supplies its address at build time.
const siteUrl =
  process.env.SITE_URL ??
  (process.env.VERCEL_PROJECT_PRODUCTION_URL
    ? `https://${process.env.VERCEL_PROJECT_PRODUCTION_URL}`
    : "http://localhost:3000");

const description =
  "Describe a telehealth visit and pick a date. TeleCompass says whether it is allowed and " +
  "payable, with the exact words of the law behind each answer.";

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl),
  title: {
    default: "TeleCompass: a preflight check for telehealth visits",
    template: "%s | TeleCompass",
  },
  description,
  openGraph: { title: "TeleCompass", description, siteName: "TeleCompass", type: "website" },
  twitter: { card: "summary_large_image", title: "TeleCompass", description },
};

async function lastFetched(): Promise<string | null> {
  try {
    const response = await fetch(`${apiUrl()}/health`);
    const body = await response.json();
    return body.notice.sources_last_fetched ?? null;
  } catch {
    return null; // the API is asleep or unreachable; the page still renders
  }
}

async function SourcesDate() {
  await connection(); // asked at request time, never at build time
  const fetched = await lastFetched();
  return fetched ? (
    <span className="font-mono">{formatDate(fetched)}</span>
  ) : (
    <span>unavailable right now</span>
  );
}

function Mark() {
  return (
    <svg viewBox="0 0 24 24" className="size-6" aria-hidden="true">
      <circle cx="12" cy="12" r="10.25" fill="none" stroke="currentColor" strokeWidth="1.5" />
      <path d="M12 4.5 14.2 12h-4.4z" fill="var(--signal)" />
      <path d="M9.8 12h4.4L12 19.5z" fill="none" stroke="currentColor" strokeWidth="1.3" />
    </svg>
  );
}

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${schibsted.variable} ${fragment.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:bg-sheet focus:px-3 focus:py-2"
        >
          Skip to the check
        </a>
        <div className="border-b border-ink/80 bg-ink text-[13px] text-white">
          <div className="mx-auto flex w-full max-w-[84rem] flex-wrap items-center gap-x-5 gap-y-1 px-4 py-2 sm:px-6">
            <p className="font-semibold">Not legal advice.</p>
            <p className="text-white/85 sm:border-l sm:border-white/25 sm:pl-5">
              Sources last fetched{" "}
              <Suspense fallback={<span>…</span>}>
                <SourcesDate />
              </Suspense>
            </p>
            <p className="hidden text-white/85 sm:block sm:border-l sm:border-white/25 sm:pl-5">
              Florida law and federal Medicare
            </p>
          </div>
        </div>
        <header className="border-b border-rule">
          <div className="mx-auto flex w-full max-w-[84rem] items-center justify-between gap-4 px-4 py-4 sm:px-6">
            <Link href="/" className="flex items-center gap-2.5 text-[19px] font-semibold tracking-[-0.02em]">
              <Mark />
              TeleCompass
            </Link>
            <Link href="/#how" className="text-[14px] font-medium underline decoration-rule-strong hover:decoration-ink">
              How answers are made
            </Link>
          </div>
        </header>
        <main id="main" className="mx-auto w-full max-w-[84rem] flex-1 px-4 py-8 sm:px-6 sm:py-10">
          {children}
        </main>
        <footer className="border-t border-rule bg-sheet">
          <div className="mx-auto grid w-full max-w-[84rem] gap-4 px-4 py-6 text-[14px] text-ink-soft sm:grid-cols-[minmax(0,1fr)_auto] sm:px-6">
            <div className="max-w-[70ch] space-y-1.5">
              <p>
                <strong className="text-ink">Not legal advice.</strong> TeleCompass shows what the law
                it has read says, and says so when it holds no rule. Every example visit is invented; no
                patient data is used or stored.
              </p>
              <p>
                Policy index: the{" "}
                <a className="underline" href="https://www.cchpca.org/" target="_blank" rel="noreferrer">
                  Center for Connected Health Policy
                </a>
                , used as a map to the law and not republished.
              </p>
            </div>
            <div className="space-y-1.5 sm:text-right">
              <p>Built by Aditya Kanbargi.</p>
              <p>
                <a
                  className="underline"
                  href="https://github.com/adikan2k/TeleCompass-AI-Powered-Telehealth-Policy-Intelligence-Platform"
                  target="_blank"
                  rel="noreferrer"
                >
                  Source code
                </a>
              </p>
            </div>
          </div>
        </footer>
      </body>
    </html>
  );
}
