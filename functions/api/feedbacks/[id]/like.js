const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
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

function publicFeedback(row) {
  return {
    id: row.id,
    content: row.content,
    display_name: row.display_name || "匿名用户",
    like_count: Number(row.like_count || 0),
    created_at: row.created_at,
  };
}

export async function onRequestOptions() {
  return new Response(null, { headers: corsHeaders });
}

export async function onRequestPost(context) {
  try {
    if (!context.env.FEEDBACK_DB) {
      return jsonResponse({ error: "missing FEEDBACK_DB" }, 503);
    }
    const id = context.params.id;
    await context.env.FEEDBACK_DB
      .prepare("UPDATE feedbacks SET like_count = like_count + 1 WHERE id = ? AND deleted_at IS NULL")
      .bind(id)
      .run();
    const row = await context.env.FEEDBACK_DB
      .prepare(
        `SELECT id, content, display_name, like_count, created_at
         FROM feedbacks
         WHERE id = ? AND deleted_at IS NULL`,
      )
      .bind(id)
      .first();
    if (!row) return jsonResponse({ error: "not found" }, 404);
    return jsonResponse({ feedback: publicFeedback(row) });
  } catch (error) {
    return jsonResponse({ error: "feedback like failed", message: String(error?.message || error) }, 500);
  }
}
