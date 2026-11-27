// Dates are always shown in one absolute, unambiguous form: "27 Nov 2026".

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const MONTHS_LONG = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

function parts(iso: string): [number, number, number] {
  const [year, month, day] = iso.slice(0, 10).split("-").map(Number);
  return [year, month, day];
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const [year, month, day] = parts(iso);
  return `${day} ${MONTHS[month - 1]} ${year}`;
}

/** The engine writes dates as 2028-01-01; people read them as 1 Jan 2028. */
export function readable(text: string): string {
  return text.replace(/\b(\d{4}-\d{2}-\d{2})\b/g, (iso) => formatDate(iso));
}

export function monthName(iso: string): string {
  return MONTHS_LONG[parts(iso)[1] - 1];
}

export function yearOf(iso: string): number {
  return parts(iso)[0];
}

/** The day after a date, as YYYY-MM-DD: a rule that ends on the 31st changes things on the 1st. */
export function dayAfter(iso: string): string {
  const [year, month, day] = parts(iso);
  const next = new Date(Date.UTC(year, month - 1, day + 1));
  return next.toISOString().slice(0, 10);
}

/** The host of a link, without "www.", to name a source in a few characters. */
export function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}
