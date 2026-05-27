import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import express, { type Router } from "express";
import MarkdownIt from "markdown-it";

export interface UsageOptions {
  /** Filesystem path to USAGE.md. */
  usagePath?: string;
}

const DEFAULT_USAGE_PATH = path.resolve(
  path.dirname(new URL(import.meta.url).pathname),
  "../../USAGE.md",
);

/** Build the router that serves the rendered USAGE.md at /. */
export function mountUsage(opts: UsageOptions = {}): Router {
  const router = express.Router();
  const usagePath = opts.usagePath ?? DEFAULT_USAGE_PATH;
  const html = renderUsage(usagePath);
  router.get("/", (_req, res) => {
    res.status(200).type("text/html").send(html);
  });
  return router;
}

function renderUsage(usagePath: string): string {
  let markdown = "";
  if (existsSync(usagePath)) {
    markdown = readFileSync(usagePath, "utf8");
  } else {
    markdown =
      "# Architecture validation service\n\n" +
      "USAGE.md not bundled in this image. See https://github.com/pvginkel/Architecture.\n";
  }

  const md = new MarkdownIt({ html: false, linkify: true, breaks: false });
  const body = md.render(markdown);
  return wrap(body);
}

function wrap(body: string): string {
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Architecture validation service</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
${STYLE}
</style>
</head>
<body>
<main>
${body}
</main>
</body>
</html>
`;
}

const STYLE = `
:root {
  color-scheme: light dark;
  --fg: #1b1f24;
  --bg: #ffffff;
  --muted: #57606a;
  --rule: #d0d7de;
  --code-bg: #f4f4f5;
  --link: #0969da;
}
@media (prefers-color-scheme: dark) {
  :root {
    --fg: #e6edf3;
    --bg: #0d1117;
    --muted: #8b949e;
    --rule: #30363d;
    --code-bg: #161b22;
    --link: #4493f8;
  }
}
html, body { background: var(--bg); color: var(--fg); }
body {
  margin: 0;
  font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  font-size: 16px;
  line-height: 1.55;
}
main {
  max-width: 50rem;
  margin: 0 auto;
  padding: 2rem 1.25rem 4rem;
}
h1, h2, h3, h4 {
  line-height: 1.25;
  margin-top: 2em;
  margin-bottom: 0.6em;
  font-weight: 600;
}
h1 { font-size: 1.75rem; margin-top: 0; }
h2 { font-size: 1.35rem; border-bottom: 1px solid var(--rule); padding-bottom: 0.3em; }
h3 { font-size: 1.1rem; }
p, ul, ol, table, pre { margin: 0.8em 0; }
a { color: var(--link); text-decoration: none; }
a:hover { text-decoration: underline; }
code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.92em;
  background: var(--code-bg);
  padding: 0.1em 0.35em;
  border-radius: 4px;
}
pre {
  background: var(--code-bg);
  padding: 0.9em 1em;
  border-radius: 6px;
  overflow-x: auto;
  font-size: 0.88rem;
}
pre code {
  background: transparent;
  padding: 0;
  font-size: inherit;
}
table {
  border-collapse: collapse;
  width: 100%;
}
th, td {
  border: 1px solid var(--rule);
  padding: 0.4em 0.7em;
  text-align: left;
  vertical-align: top;
}
th { background: var(--code-bg); font-weight: 600; }
blockquote {
  margin: 1em 0;
  padding: 0 1em;
  color: var(--muted);
  border-left: 4px solid var(--rule);
}
hr { border: 0; border-top: 1px solid var(--rule); margin: 2em 0; }
`;
