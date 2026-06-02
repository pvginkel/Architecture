import express, { type Router } from "express";

export interface LayoutProxyOptions {
  /**
   * Base URL of the elk-layout-service. Defaults to LAYOUT_SERVICE_URL.
   * When neither is set, /api/layout responds 503 — the rest of the service
   * still runs without a layout backend wired up.
   */
  target?: string;
  /** Max body size in bytes. Defaults to 8 MiB — the everything-view graph is
   *  small (ids + ints), but headroom is cheap. */
  bodyLimit?: number;
}

const DEFAULT_LIMIT = 8 * 1024 * 1024;

/**
 * Proxies POST /api/layout to the (unauthenticated, local-network)
 * elk-layout-service. The browser never talks to the layout service directly;
 * it goes through this same-origin endpoint, so no CORS and one place to point
 * at the backend.
 */
export function mountLayoutProxy(opts: LayoutProxyOptions = {}): Router {
  const router = express.Router();
  const target = opts.target ?? process.env.LAYOUT_SERVICE_URL;
  const limit = opts.bodyLimit ?? DEFAULT_LIMIT;

  router.post(
    "/api/layout",
    express.raw({ limit, type: () => true }),
    async (req, res) => {
      if (!target) {
        res.status(503).json({ error: "layout service not configured (set LAYOUT_SERVICE_URL)" });
        return;
      }

      const body = (req.body as Buffer | undefined) ?? Buffer.alloc(0);
      let upstream: Response;
      try {
        upstream = await fetch(new URL("/layout", target), {
          method: "POST",
          headers: { "Content-Type": req.headers["content-type"] ?? "application/json" },
          body,
        });
      } catch (e) {
        res.status(502).json({ error: `layout service unreachable: ${(e as Error).message}` });
        return;
      }

      const payload = Buffer.from(await upstream.arrayBuffer());
      res
        .status(upstream.status)
        .type(upstream.headers.get("content-type") ?? "application/json")
        .send(payload);
    },
  );

  return router;
}
