import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import { connection } from "next/server";
import { Suspense } from "react";

import { apiUrl } from "@/lib/api";

import "./globals.css";

const geistSans = Geist({ variable: "--font-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

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

// The date the law was last fetched, asked of the API on each request.
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
  await connection(); // always asked at request time, never at build time
  const fetched = await lastFetched();
  return fetched
    ? `Sources last fetched ${fetched}.`
    : "The date the sources were last fetched is unavailable right now.";
}

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col">
        <header className="border-b border-border bg-primary text-primary-foreground">
          <div className="mx-auto flex w-full max-w-6xl flex-wrap items-center justify-between gap-2 px-4 py-3">
            <Link href="/" className="flex items-center gap-2 text-lg font-semibold">
              <svg viewBox="0 0 24 24" className="size-6" aria-hidden="true">
                <circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" strokeWidth="1.5" />
                <path d="M15.5 8.5 13.4 13.4 8.5 15.5l2.1-4.9z" fill="currentColor" />
              </svg>
              TeleCompass
            </Link>
            <p className="text-sm">A preflight check for telehealth visits</p>
          </div>
        </header>
        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">{children}</main>
        <footer className="border-t border-border bg-card">
          <div className="mx-auto w-full max-w-6xl space-y-1 px-4 py-4 text-sm text-muted-foreground">
            <p>
              <strong className="text-foreground">Not legal advice.</strong>{" "}
              <Suspense fallback="Checking when the sources were last fetched…">
                <SourcesDate />
              </Suspense>{" "}
              TeleCompass shows what the law it has read says, and says so when it holds no rule.
            </p>
            <p>
              Built by Aditya Kanbargi. Policy index: the{" "}
              <a
                className="underline underline-offset-2"
                href="https://www.cchpca.org/"
                target="_blank"
                rel="noreferrer"
              >
                Center for Connected Health Policy
              </a>
              . Every example visit is invented; no patient data is used or stored.
            </p>
          </div>
        </footer>
      </body>
    </html>
  );
}
