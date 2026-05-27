import type { RequestHandler } from "express";

/**
 * Ported from viewer/nginx.conf: webathome.org (apex + www) and the
 * dev-VM origin are allowed to embed the viewer in an iframe.
 */
const FRAME_ANCESTORS =
  "frame-ancestors 'self' https://webathome.org https://www.webathome.org http://wrkdev:4321";

export function viewerCsp(): RequestHandler {
  return (_req, res, next) => {
    res.setHeader("Content-Security-Policy", FRAME_ANCESTORS);
    next();
  };
}
