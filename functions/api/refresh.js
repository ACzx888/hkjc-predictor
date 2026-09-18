/**
 * Cloudflare Pages Function: POST /api/refresh
 * Triggers a new Pages build via Deploy Hook (env DEPLOY_HOOK_URL).
 * Secrets stay in Pages env — never commit the hook URL.
 */
export async function onRequestPost(context) {
  const hook = context.env.DEPLOY_HOOK_URL;
  if (!hook) {
    return Response.json(
      {
        ok: false,
        triggered: false,
        error: "DEPLOY_HOOK_URL is not configured in Pages environment variables",
      },
      { status: 500 }
    );
  }

  try {
    const res = await fetch(hook, { method: "POST" });
    const triggered = res.ok;
    const body = {
      ok: triggered,
      triggered,
    };
    if (!triggered) {
      body.error = `Deploy hook HTTP ${res.status}`;
    }
    return Response.json(body, { status: triggered ? 200 : 502 });
  } catch (err) {
    return Response.json(
      {
        ok: false,
        triggered: false,
        error: String(err && err.message ? err.message : err),
      },
      { status: 500 }
    );
  }
}

/** Optional: allow GET to explain usage (no trigger). */
export async function onRequestGet() {
  return Response.json({
    ok: true,
    triggered: false,
    hint: "POST /api/refresh to trigger a Cloudflare Pages rebuild via DEPLOY_HOOK_URL",
  });
}
