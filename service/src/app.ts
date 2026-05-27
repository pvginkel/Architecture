import express, { type Express } from "express";

export function createApp(): Express {
  const app = express();

  app.get("/healthz", (_req, res) => {
    res.status(200).type("text/plain").send("ok");
  });

  return app;
}
