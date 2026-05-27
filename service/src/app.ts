import express, { type Express } from "express";
import { loadSchemas, type SchemaBundle } from "./schema-loader.js";
import { mountStatic, resolveViewerRoot } from "./static.js";
import { mountValidate } from "./validate.js";

export interface AppOptions {
  /** Schema bundle. Defaults to loading from the repo's schema/v0.1/. */
  bundle?: SchemaBundle;
  /** Filesystem path to the built viewer. Defaults to resolveViewerRoot(). */
  viewerRoot?: string;
}

export function createApp(opts: AppOptions = {}): Express {
  const app = express();
  const bundle = opts.bundle ?? loadSchemas();
  const viewerRoot = opts.viewerRoot ?? resolveViewerRoot();

  app.get("/healthz", (_req, res) => {
    res.status(200).type("text/plain").send("ok");
  });

  app.use(mountStatic({ viewerRoot, bundle }));
  app.use(mountValidate({ bundle }));

  return app;
}
