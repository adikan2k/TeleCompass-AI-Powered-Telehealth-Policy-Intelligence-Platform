import Link from "next/link";

export default function NotFound() {
  return (
    <div className="max-w-[60ch] space-y-4">
      <h1 className="text-[40px] leading-[1.05] font-medium tracking-[-0.035em]">No answer at this address</h1>
      <p className="text-[16px] text-ink-soft">
        There is no stored answer or page here. The link may be mistyped or cut short.
      </p>
      <Link
        href="/"
        className="press notch inline-flex min-h-11 items-center bg-ink px-4 text-[15px] font-semibold text-white"
      >
        Check a visit
      </Link>
    </div>
  );
}
