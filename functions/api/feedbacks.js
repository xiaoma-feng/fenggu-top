const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
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

function text(value) {
  return String(value ?? "").trim();
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

function requireDb(env) {
  if (!env.FEEDBACK_DB) {
    throw new Error("Missing D1 binding FEEDBACK_DB");
  }
  return env.FEEDBACK_DB;
}

export async function onRequestOptions() {
  return new Response(null, { headers: corsHeaders });
}

export async function onRequestGet(context) {
  try {
    const db = requireDb(context.env);
    const limit = Math.min(50, Math.max(1, Number(new URL(context.request.url).searchParams.get("limit") || 30)));
    const result = await db
      .prepare(
        `SELECT id, content, display_name, like_count, created_at
         FROM feedbacks
         WHERE deleted_at IS NULL
         ORDER BY created_at DESC
         LIMIT ?`,
      )
      .bind(limit)
      .all();
    return jsonResponse({ feedbacks: (result.results || []).map(publicFeedback) });
  } catch (error) {
    return jsonResponse({ error: "feedback unavailable", message: String(error?.message || error) }, 503);
  }
}

export async function onRequestPost(context) {
  try {
    const db = requireDb(context.env);
    const body = await context.request.json().catch(() => ({}));
    const content = text(body.content).slice(0, 300);
    const displayName = text(body.display_name).slice(0, 20) || "匿名用户";
    if (!content) return jsonResponse({ error: "content required" }, 400);

    const feedback = {
      id: crypto.randomUUID(),
      content,
      display_name: displayName,
      like_count: 0,
      created_at: new Date().toISOString(),
    };
    await db
      .prepare(
        `INSERT INTO feedbacks (id, content, display_name, like_count, created_at, deleted_at)
         VALUES (?, ?, ?, ?, ?, NULL)`,
      )
      .bind(feedback.id, feedback.content, feedback.display_name, feedback.like_count, feedback.created_at)
      .run();
    return jsonResponse({ feedback: publicFeedback(feedback) }, 201);
  } catch (error) {
    return jsonResponse({ error: "feedback create failed", message: String(error?.message || error) }, 500);
  }
}
