import {
  corsHeaders,
  jsonResponse,
  publicFeedback,
  readFeedbacks,
  writeFeedbacks,
} from "../../../_lib/feedback-store.js";

export function onRequestOptions() {
  return new Response(null, { headers: corsHeaders });
}

export async function onRequestPost(context) {
  try {
    const rows = await readFeedbacks(context);
    const index = rows.findIndex((row) => String(row.id) === String(context.params.id));
    if (index < 0) return jsonResponse({ error: "not found" }, 404);
    const updated = {
      ...rows[index],
      like_count: Number(rows[index].like_count || 0) + 1,
    };
    rows[index] = updated;
    await writeFeedbacks(context, rows);
    return jsonResponse({ feedback: publicFeedback(updated) });
  } catch (error) {
    return jsonResponse({ error: "feedback like failed", message: String(error?.message || error) }, 500);
  }
}
