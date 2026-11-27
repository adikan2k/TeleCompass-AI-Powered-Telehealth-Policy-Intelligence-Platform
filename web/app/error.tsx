"use client"; // Error boundaries must be Client Components

export default function Error({ retry }: { error: unknown; retry: () => void }) {
  return (
    <div className="max-w-[60ch] space-y-4">
      <h1 className="text-[40px] leading-[1.05] font-medium tracking-[-0.035em]">That did not load</h1>
      <p className="text-[16px] text-ink-soft">
        The service behind this page did not answer. It may be starting up after a quiet spell. Try
        again in a few seconds.
      </p>
      <button
        type="button"
        onClick={() => retry()}
        className="press notch inline-flex min-h-11 items-center bg-ink px-4 text-[15px] font-semibold text-white"
      >
        Try again
      </button>
    </div>
  );
}
