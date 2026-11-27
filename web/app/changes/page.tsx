import type { Metadata } from "next";

import { ChangesApp } from "@/components/changes-app";

const description =
  "Pick the states you serve and your line of care. See what changed in the policy since the last " +
  "copy, which rule changes a person approved, and which rules start or end soon.";

export const metadata: Metadata = {
  title: "What changed for you",
  description,
  openGraph: { title: "TeleCompass: what changed for you", description },
};

export default function Page() {
  return (
    <div className="space-y-10">
      <div className="max-w-[62rem] space-y-4">
        <h1 className="max-w-[20ch] text-[40px] leading-[1.02] font-medium tracking-[-0.035em] sm:text-[54px]">
          What changed for you
        </h1>
        <p className="max-w-[62ch] text-[17px] text-ink-soft">
          Each month the policy page is copied again and compared with the last copy. A change becomes a
          proposed rule, and it reaches the answers only once a person approves it. Rules with an end date are
          listed before they end.
        </p>
      </div>
      <ChangesApp />
    </div>
  );
}
