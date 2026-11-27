"use client"; // Error boundaries must be Client Components

import { Button } from "@/components/ui/button";

export default function Error({ retry }: { error: unknown; retry: () => void }) {
  return (
    <div className="max-w-2xl space-y-3">
      <h1 className="text-3xl font-semibold tracking-tight">That did not load</h1>
      <p className="text-base text-muted-foreground">
        The service behind this page did not answer. It may be waking up. Please try again.
      </p>
      <Button type="button" onClick={() => retry()}>
        Try again
      </Button>
    </div>
  );
}
