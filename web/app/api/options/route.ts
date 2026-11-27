import { apiUrl } from "@/lib/api";

// Passes the form's choices through from the API. Reading the request makes this run per
// request, never at build time.
export async function GET(request: Request) {
  const accept = request.headers.get("accept") ?? "application/json";
  let response: Response;
  try {
    response = await fetch(`${apiUrl()}/options`, { headers: { accept } });
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
