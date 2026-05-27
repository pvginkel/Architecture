import { existsSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import express, { type Router, type RequestHandler } from "express";
import type { SchemaBundle, StaticFile } from "./schema-loader.js";
import { viewerCsp } from "./csp.js";

export interface StaticOptions {
  /** Filesystem path to the built viewer (containing index.html). */
  viewerRoot: string;
  /** Schema bundle from loadSchemas(). */
  bundle: SchemaBundle;
}

const CACHE_ASSETS = "public, max-age=31536000, immutable";
const CACHE_LOGOS = "public, max-age=86400";
const CACHE_HTML = "no-cache";
const CACHE_SCHEMA = "public, max-age=300";

/**
 * Mounts /viewer/* and /schema/v0.1/* on the given router. Returns it so the
 * caller can wire it into the Express app.
 */
export function mountStatic(opts: StaticOptions): Router {
  const router = express.Router();
  mountViewer(router, opts.viewerRoot);
  mountSchema(router, opts.bundle);
  return router;
}

function mountViewer(router: Router, viewerRoot: string): void {
  const csp = viewerCsp();

  // Path-specific cache headers, mirroring viewer/nginx.conf.
  const cacheHeader: RequestHandler = (req, res, next) => {
    const p = req.path;
    if (p.startsWith("/assets/")) {
      res.setHeader("Cache-Control", CACHE_ASSETS);
    } else if (p.startsWith("/logos/")) {
      res.setHeader("Cache-Control", CACHE_LOGOS);
    } else if (p.endsWith(".html") || p === "/" || p === "") {
      res.setHeader("Cache-Control", CACHE_HTML);
    }
    next();
  };

  router.use("/viewer", csp, cacheHeader, express.static(viewerRoot, {
    fallthrough: true,
    index: ["index.html"],
    etag: true,
  }));

  // SPA fallback — any unmatched /viewer/* path serves index.html so the
  // viewer's client-side router can take over.
  router.get(/^\/viewer(\/.*)?$/, csp, (_req, res, next) => {
    const indexPath = path.join(viewerRoot, "index.html");
    if (!existsSync(indexPath)) {
      next();
      return;
    }
    res.setHeader("Cache-Control", CACHE_HTML);
    res.type("text/html").send(readFileSync(indexPath, "utf8"));
  });
}

function mountSchema(router: Router, bundle: SchemaBundle): void {
  // Schema files served from the in-memory map: every YAML schema is also
  // available at the same path with .json as the canonical JSON form.
  router.get(/^\/schema\/v0\.1\/(.+)$/, (req, res, next) => {
    const requested = req.params[0]!;
    const served = lookupSchemaFile(bundle, requested);
    if (!served) {
      next();
      return;
    }
    setSchemaHeaders(res, served.contentType, served.file.etag);
    res.status(200).send(served.body);
  });

  // Vendored ArchiMate XSD + relationship matrix XML — served as-is from disk.
  const archimateDir = path.join(bundle.schemaRoot, "archimate");
  router.use(
    "/schema/v0.1/archimate",
    (_req, res, next) => {
      res.setHeader("Cache-Control", CACHE_SCHEMA);
      res.setHeader("Access-Control-Allow-Origin", "*");
      next();
    },
    express.static(archimateDir, {
      fallthrough: true,
      index: false,
      etag: true,
      setHeaders(res, filePath) {
        if (filePath.endsWith(".xsd") || filePath.endsWith(".xml")) {
          res.setHeader("Content-Type", "application/xml; charset=utf-8");
        }
      },
    }),
  );
}

interface ServedSchema {
  body: string;
  contentType: string;
  file: StaticFile;
}

function lookupSchemaFile(bundle: SchemaBundle, requested: string): ServedSchema | undefined {
  // Exact YAML match.
  if (requested.endsWith(".yaml") || requested.endsWith(".yml")) {
    const file = bundle.staticFiles.get(requested);
    if (!file) return undefined;
    return { body: file.yaml, contentType: "application/yaml; charset=utf-8", file };
  }
  // .json sibling for any registered .yaml.
  if (requested.endsWith(".json")) {
    const yamlPath = requested.slice(0, -".json".length) + ".yaml";
    const file = bundle.staticFiles.get(yamlPath);
    if (!file) return undefined;
    return { body: file.json, contentType: "application/schema+json; charset=utf-8", file };
  }
  return undefined;
}

function setSchemaHeaders(
  res: express.Response,
  contentType: string,
  etag: string,
): void {
  res.setHeader("Content-Type", contentType);
  res.setHeader("Cache-Control", CACHE_SCHEMA);
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("ETag", etag);
}

/**
 * Resolve the viewer-dist path. Honors VIEWER_ROOT for tests; otherwise looks
 * for ./viewer-dist (Docker layout), then ../viewer/dist (dev layout).
 */
export function resolveViewerRoot(cwd: string = process.cwd()): string {
  if (process.env.VIEWER_ROOT) return process.env.VIEWER_ROOT;
  const candidates = [
    path.join(cwd, "viewer-dist"),
    path.join(cwd, "..", "viewer", "dist"),
  ];
  for (const c of candidates) {
    if (existsSync(c) && statSync(c).isDirectory()) return c;
  }
  return candidates[0]!;
}
