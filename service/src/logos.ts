import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import express, { type Router } from "express";

export interface LogosOptions {
  /** Filesystem path to the built viewer (containing the logos/ directory). */
  viewerRoot: string;
}

const CACHE_LOGOS = "public, max-age=86400";
const LOGO_EXTENSIONS = [".svg", ".png"];

const CONTENT_TYPES: Record<string, string> = {
  ".svg": "image/svg+xml",
  ".png": "image/png",
};

/**
 * Scan viewerRoot/logos/, returning a bare-name → filename map.
 *
 * Mirrors tooling/generate.py::scan_logo_library: only .svg/.png files are
 * logos (titles.json and anything else is skipped); the bare name is the file
 * stem. A stem present under two extensions (e.g. both foo.svg and foo.png) is
 * ambiguous — raise rather than silently pick one.
 */
function scanLogoLibrary(viewerRoot: string): Map<string, string> {
  const logosDir = path.join(viewerRoot, "logos");
  const mapping = new Map<string, string>();
  // A missing logos/ dir throws (ENOENT → 500) by design: it's a real
  // misconfiguration, not a condition to swallow. Fail loud per the
  // subproject's no-defensive-coding philosophy rather than guard it.
  for (const entry of readdirSync(logosDir).sort()) {
    const ext = path.extname(entry);
    if (!LOGO_EXTENSIONS.includes(ext)) continue;
    const stem = path.basename(entry, ext);
    const existing = mapping.get(stem);
    if (existing) {
      throw new Error(
        `logo library name collision: '${stem}' exists as both '${existing}' ` +
          `and '${entry}' — a bare-name reference would be ambiguous. ` +
          `Remove one of the two files.`,
      );
    }
    mapping.set(stem, entry);
  }
  return mapping;
}

/**
 * Mounts GET /api/logo?name=<name>, resolving a bare (extensionless) logo name
 * to its image under viewerRoot/logos/ and serving the raw bytes with the
 * matching Content-Type.
 *
 * `name` is untrusted: it is only ever resolved through the directory's
 * stem→filename map, never path-joined into a filesystem path, so a name with
 * slashes / dots / `..` simply misses the map and 404s.
 */
export function mountLogos(opts: LogosOptions): Router {
  const router = express.Router();
  const logosDir = path.join(opts.viewerRoot, "logos");

  router.get("/api/logo", (req, res, next) => {
    const name = req.query.name;
    if (typeof name !== "string") {
      next();
      return;
    }

    const filename = scanLogoLibrary(opts.viewerRoot).get(name);
    if (!filename) {
      next();
      return;
    }

    const ext = path.extname(filename);
    const body = readFileSync(path.join(logosDir, filename));
    res.setHeader("Cache-Control", CACHE_LOGOS);
    res.type(CONTENT_TYPES[ext]!).status(200).send(body);
  });

  return router;
}
