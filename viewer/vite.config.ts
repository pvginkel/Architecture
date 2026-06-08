import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { defineConfig, type Plugin } from "vite";
import { parse as parseYaml } from "yaml";
import react from "@vitejs/plugin-react";

// Production manifest the viewer reads in prod. In dev we fetch this for its
// (live) element/relation data but swap in the views we are actively editing.
const LIVE_MANIFEST_URL =
  "https://architecture.webathome.org/data/v0.1/architecture.json";
// The authored view files live one level up, in the repo's views/ directory.
const VIEWS_DIR = fileURLToPath(new URL("../views", import.meta.url));

/** The authored views, in the order _order.yaml declares — the same set and
 *  order the collector inlines into the production manifest, minus the schema
 *  validation (that is CI's job; dev just wants the current files, fast). */
function readAuthoredViews(): { id: string }[] {
  const order = parseYaml(readFileSync(`${VIEWS_DIR}/_order.yaml`, "utf8"))
    .order as string[];
  const byId = new Map<string, { id: string }>();
  for (const file of readdirSync(VIEWS_DIR)) {
    if (file === "_order.yaml" || !file.endsWith(".yaml")) {
      continue;
    }
    const doc = parseYaml(readFileSync(`${VIEWS_DIR}/${file}`, "utf8")) as {
      id: string;
    };
    byId.set(doc.id, doc);
  }
  return order.map((id) => {
    const view = byId.get(id);
    if (!view) {
      throw new Error(
        `dev manifest: _order.yaml lists '${id}' but views/${id}.yaml is missing`,
      );
    }
    return view;
  });
}

// Dev-only endpoint: the live production manifest with its views collection
// replaced by the authored views in this checkout. This is the dev `src`, so the
// viewer always renders current data against the views we are editing — no more
// hand-refreshing a committed snapshot. The synthesised `everything` view is not
// authored under views/, so it is carried over from the live manifest.
function devLiveManifestPlugin(): Plugin {
  return {
    name: "dev-live-manifest-with-local-views",
    apply: "serve",
    configureServer(server) {
      server.middlewares.use("/dev/architecture.json", async (_req, res) => {
        try {
          const response = await fetch(LIVE_MANIFEST_URL);
          if (!response.ok) {
            throw new Error(
              `live manifest fetch failed: ${response.status} ${response.statusText}`,
            );
          }
          const manifest = (await response.json()) as { views: { id: string }[] };
          const everything = manifest.views.find((view) => view.id === "everything");
          const authored = readAuthoredViews();
          manifest.views = everything ? [...authored, everything] : authored;
          res.setHeader("Content-Type", "application/json");
          res.setHeader("Cache-Control", "no-store");
          res.end(JSON.stringify(manifest));
        } catch (error) {
          // Loud boundary: surface the failure as a 502 with the message so the
          // viewer's load-error panel shows it, rather than degrading silently.
          res.statusCode = 502;
          res.end(error instanceof Error ? error.message : String(error));
        }
      });
    },
  };
}

export default defineConfig({
  base: "/viewer/",
  plugins: [react(), devLiveManifestPlugin()],
  build: {
    outDir: "dist",
    sourcemap: false,
  },
  server: {
    host: true,
    port: 5173,
    allowedHosts: ["wrkdev"],
  },
});
