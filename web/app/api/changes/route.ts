import { apiUrl } from "@/lib/api";

// Passes "what changed" through from the API, with the same two choices and nothing else.
export async function GET(request: Request) {
  const asked = new URL(request.url).searchParams;
  const query = new URLSearchParams();
  query.set("states", asked.get("states") ?? "FL");
  query.set("care", asked.get("care") ?? "behavioral_health");
  let response: Response;
  try {
    response = await fetch(`${apiUrl()}/changes?${query}`, {
      headers: { accept: "application/json" },
    });
  } catch {
    return Response.json(
      {
        error: "The service is not reachable right now. Please try again in a minute.",
      },
      { status: 502 },
    );
  }
  return new Response(await response.text(), {
    status: response.status,
    headers: { "content-type": "application/json" },
  });
}
