const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "DELETE, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, X-Admin-Token",
};

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      ...corsHeaders,
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}

export async function onRequestOptions() {
  return new Response(null, { headers: corsHeaders });
}

export async function onRequestDelete(context) {
  try {
    const token = context.request.headers.get("X-Admin-Token") || "";
    if (!context.env.FEEDBACK_ADMIN_TOKEN || token !== context.env.FEEDBACK_ADMIN_TOKEN) {
      return jsonResponse({ error: "unauthorized" }, 401);
    }
    if (!context.env.FEEDBACK_DB) {
      return jsonResponse({ error: "missing FEEDBACK_DB" }, 503);
    }
    const id = context.params.id;
    await context.env.FEEDBACK_DB
      .prepare("UPDATE feedbacks SET deleted_at = ? WHERE id = ?")
      .bind(new Date().toISOString(), id)
      .run();
    return jsonResponse({ ok: true });
  } catch (error) {
    return jsonResponse({ error: "feedback delete failed", message: String(error?.message || error) }, 500);
  }
}
