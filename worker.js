/** Serve static assets; force UTF-8 charset on tip sheets (Workers omit charset by default). */
export default {
  async fetch(request, env) {
    const response = await env.ASSETS.fetch(request);
    const path = new URL(request.url).pathname.toLowerCase();
    if (!(path.endsWith(".md") || path.endsWith(".txt") || path.endsWith(".json"))) {
      return response;
    }
    const headers = new Headers(response.headers);
    if (path.endsWith(".md")) {
      headers.set("Content-Type", "text/markdown; charset=utf-8");
    } else if (path.endsWith(".txt")) {
      headers.set("Content-Type", "text/plain; charset=utf-8");
    } else if (path.endsWith(".json")) {
      headers.set("Content-Type", "application/json; charset=utf-8");
    }
    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers,
    });
  },
};
