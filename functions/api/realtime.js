import worker from "../../workers/realtime.js";

export async function onRequest(context) {
  return worker.fetch(context.request, context.env, context);
}
