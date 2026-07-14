import {
  cleanText,
  corsHeaders,
  jsonResponse,
  publicFeedback,
  readFeedbacks,
  writeFeedbacks,
} from "../_lib/feedback-store.js";

export function onRequestOptions() {
  return new Response(null, { headers: corsHeaders });
}

export async function onRequestGet(context) {
  try {
    const limit = Math.min(50, Math.max(1, Number(new URL(context.request.url).searchParams.get("limit") || 30)));
    const rows = await readFeedbacks(context);
    return jsonResponse({ feedbacks: rows.slice(0, limit).map(publicFeedback) });
  } catch (error) {
    return jsonResponse({ error: "feedback unavailable", message: String(error?.message || error) }, 503);
  }
}

export async function onRequestPost(context) {
  try {
    const body = await context.request.json().catch(() => ({}));
    const content = cleanText(body.content, 300);
    if (!content) return jsonResponse({ error: "content required" }, 400);

    const feedback = {
      id: crypto.randomUUID(),
      content,
      display_name: cleanText(body.display_name, 20) || "匿名用户",
      like_count: 0,
      created_at: new Date().toISOString(),
    };
    const rows = await readFeedbacks(context);
    await writeFeedbacks(context, [feedback, ...rows]);
    return jsonResponse({ feedback: publicFeedback(feedback) }, 201);
  } catch (error) {
    return jsonResponse({ error: "feedback create failed", message: String(error?.message || error) }, 500);
  }
}
