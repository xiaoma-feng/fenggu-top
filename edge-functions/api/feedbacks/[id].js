import {
  corsHeaders,
  jsonResponse,
  readFeedbacks,
  writeFeedbacks,
} from "../../_lib/feedback-store.js";

export function onRequestOptions() {
  return new Response(null, { headers: corsHeaders });
}

export async function onRequestDelete(context) {
  try {
    const token = context.request.headers.get("X-Admin-Token") || "";
    if (!context.env?.FEEDBACK_ADMIN_TOKEN || token !== context.env.FEEDBACK_ADMIN_TOKEN) {
      return jsonResponse({ error: "unauthorized" }, 401);
    }
    const rows = await readFeedbacks(context);
    const next = rows.filter((row) => String(row.id) !== String(context.params.id));
    if (next.length === rows.length) return jsonResponse({ error: "not found" }, 404);
    await writeFeedbacks(context, next);
    return jsonResponse({ ok: true });
  } catch (error) {
    return jsonResponse({ error: "feedback delete failed", message: String(error?.message || error) }, 500);
  }
}
