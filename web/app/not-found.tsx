import Link from "next/link";

export default function NotFound() {
  return (
    <div className="max-w-2xl space-y-3">
      <h1 className="text-3xl font-semibold tracking-tight">Nothing at this address</h1>
      <p className="text-base text-muted-foreground">
        There is no stored answer or page here. The link may be mistyped.
      </p>
      <Link href="/" className="font-medium text-primary underline underline-offset-2">
        Check a visit
      </Link>
    </div>
  );
}
