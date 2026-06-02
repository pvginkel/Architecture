import express, { type Express } from "express";
import { loadSchemas, SchemaLoadError, type SchemaBundle } from "./schema-loader.js";
import { mountStatic, resolveViewerRoot, resolveDataRoot } from "./static.js";
import { mountValidate } from "./validate.js";
import { mountLayoutProxy } from "./layout-proxy.js";
import { createMetrics, mountMetrics, type Metrics } from "./metrics.js";
import { mountUsage } from "./usage.js";

export interface AppOptions {
  /** Schema bundle. Defaults to loading from the repo's schema/v0.1/. */
  bundle?: SchemaBundle;
  /** Filesystem path to the built viewer. Defaults to resolveViewerRoot(). */
  viewerRoot?: string;
  /** Filesystem path to the merged-dataset directory. Defaults to resolveDataRoot(). */
  dataRoot?: string;
  /** Metrics sink. Defaults to a fresh registry. */
  metrics?: Metrics;
  /** Filesystem path to USAGE.md. Defaults to the repo root copy. */
  usagePath?: string;
  /** Base URL of the elk-layout-service. Defaults to LAYOUT_SERVICE_URL. */
  layoutServiceUrl?: string;
}

export function createApp(opts: AppOptions = {}): Express {
  const app = express();
  const metrics = opts.metrics ?? createMetrics();
  const bundle = opts.bundle ?? loadBundleOrCount(metrics);
  const viewerRoot = opts.viewerRoot ?? resolveViewerRoot();
  const dataRoot = opts.dataRoot ?? resolveDataRoot();

  app.get("/healthz", (_req, res) => {
    res.status(200).type("text/plain").send("ok");
  });

  app.use(mountUsage({ usagePath: opts.usagePath }));
  app.use(mountStatic({ viewerRoot, bundle, dataRoot }));
  app.use(mountValidate({ bundle, metrics }));
  app.use(mountLayoutProxy({ target: opts.layoutServiceUrl }));
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
