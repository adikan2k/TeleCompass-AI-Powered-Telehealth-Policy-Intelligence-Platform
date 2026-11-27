import { apiUrl } from "@/lib/api";

// Passes a visit to the API and returns its answer. The visitor's address is forwarded so the
// API can apply its daily limit per visitor; the API keeps only a one-way hash of it.
// `?store=false` is passed through: the worked example on the home page is not stored.
export async function POST(request: Request) {
  const body = await request.text();
  const store = new URL(request.url).searchParams.get("store") === "false" ? "?store=false" : "";
  const forwarded = request.headers.get("x-forwarded-for") ?? "";
  let response: Response;
  try {
    response = await fetch(`${apiUrl()}/preflight${store}`, {
      method: "POST",
      headers: { "content-type": "application/json", "x-forwarded-for": forwarded },
      body,
    });
  } catch {
    return Response.json(
      { error: "The service is not reachable right now. Please try again in a minute." },
      { status: 502 },
    );
  }
  return new Response(await response.text(), {
    status: response.status,
    headers: { "content-type": "application/json" },
  });
}
