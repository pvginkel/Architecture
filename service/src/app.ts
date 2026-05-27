import express, { type Express } from "express";
import { loadSchemas, SchemaLoadError, type SchemaBundle } from "./schema-loader.js";
import { mountStatic, resolveViewerRoot } from "./static.js";
import { mountValidate } from "./validate.js";
import { createMetrics, mountMetrics, type Metrics } from "./metrics.js";

export interface AppOptions {
  /** Schema bundle. Defaults to loading from the repo's schema/v0.1/. */
  bundle?: SchemaBundle;
  /** Filesystem path to the built viewer. Defaults to resolveViewerRoot(). */
  viewerRoot?: string;
  /** Metrics sink. Defaults to a fresh registry. */
  metrics?: Metrics;
}

export function createApp(opts: AppOptions = {}): Express {
  const app = express();
  const metrics = opts.metrics ?? createMetrics();
  const bundle = opts.bundle ?? loadBundleOrCount(metrics);
  const viewerRoot = opts.viewerRoot ?? resolveViewerRoot();

  app.get("/healthz", (_req, res) => {
    res.status(200).type("text/plain").send("ok");
  });

  app.use(mountStatic({ viewerRoot, bundle }));
  app.use(mountValidate({ bundle, metrics }));
  app.use(mountMetrics(metrics));

  return app;
}

function loadBundleOrCount(metrics: Metrics): SchemaBundle {
  try {
    return loadSchemas();
  } catch (e) {
    if (e instanceof SchemaLoadError) {
      metrics.schemaLoadErrors.inc();
    }
    throw e;
  }
}
