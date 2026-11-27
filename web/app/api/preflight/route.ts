import { apiUrl } from "@/lib/api";

// Passes a visit to the API and returns its answer. The visitor's address is forwarded so the
// API can apply its daily limit per visitor; the API keeps only a one-way hash of it.
export async function POST(request: Request) {
  const body = await request.text();
  const forwarded = request.headers.get("x-forwarded-for") ?? "";
  let response: Response;
  try {
    response = await fetch(`${apiUrl()}/preflight`, {
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
