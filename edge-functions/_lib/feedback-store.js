const feedbackKey = "feedback_items_v1";
const maxFeedbacks = 200;

export const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, X-Admin-Token",
};

export function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      ...corsHeaders,
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}

export function cleanText(value, maxLength) {
  return String(value ?? "").trim().slice(0, maxLength);
}

export function publicFeedback(row) {
  return {
    id: row.id,
    content: row.content,
    display_name: row.display_name || "匿名用户",
    like_count: Number(row.like_count || 0),
    created_at: row.created_at,
  };
}

export function feedbackStore(context) {
  if (context?.env?.FENGGU_FEEDBACK) return context.env.FENGGU_FEEDBACK;
  if (globalThis.FENGGU_FEEDBACK) return globalThis.FENGGU_FEEDBACK;
  try {
    if (typeof FENGGU_FEEDBACK !== "undefined") return FENGGU_FEEDBACK;
  } catch {
    // The binding is configured in the EdgeOne console after project creation.
  }
  throw new Error("Missing EdgeOne KV binding FENGGU_FEEDBACK");
}

export async function readFeedbacks(context) {
  const raw = await feedbackStore(context).get(feedbackKey);
  if (!raw) return [];
  try {
    const rows = JSON.parse(String(raw));
    return Array.isArray(rows) ? rows.filter(Boolean).slice(0, maxFeedbacks) : [];
  } catch {
    return [];
  }
}

export async function writeFeedbacks(context, rows) {
  const normalized = rows
    .filter(Boolean)
    .sort((left, right) => String(right.created_at || "").localeCompare(String(left.created_at || "")))
    .slice(0, maxFeedbacks);
  await feedbackStore(context).put(feedbackKey, JSON.stringify(normalized));
  return normalized;
}
