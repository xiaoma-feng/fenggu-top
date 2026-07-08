export async function onRequest(context) {
  const response = await context.next();
  const contentType = response.headers.get("content-type") || "";
  if (!contentType.includes("text/html")) return response;

  let html = await response.text();
  if (!html.includes("/src/feedback-widget.js")) {
    html = html.replace("</head>", '  <link rel="stylesheet" href="/src/feedback-widget.css" />\n  </head>');
    html = html.replace("</body>", '  <script src="/src/feedback-widget.js"></script>\n  </body>');
  }

  const headers = new Headers(response.headers);
  headers.set("content-type", "text/html; charset=utf-8");
  headers.set("cache-control", "no-cache");
  return new Response(html, { status: response.status, headers });
}
