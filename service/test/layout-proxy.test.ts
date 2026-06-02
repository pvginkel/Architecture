import { describe, it, expect, beforeAll, afterAll } from "vitest";
import { createServer, type Server } from "node:http";
import { AddressInfo } from "node:net";
import request from "supertest";
import { createApp } from "../src/app.js";

describe("POST /api/layout", () => {
  it("503s when no layout service is configured", async () => {
    const res = await request(createApp({ layoutServiceUrl: undefined }))
      .post("/api/layout")
      .set("Content-Type", "application/json")
      .send({ nodes: [] });
    expect(res.status).toBe(503);
    expect(res.body.error).toMatch(/not configured/);
  });

  describe("with a stub upstream", () => {
    let upstream: Server;
    let received: { url?: string; body?: string } = {};
    let target: string;

    beforeAll(async () => {
      upstream = createServer((req, res) => {
        let raw = "";
        req.on("data", (c) => (raw += c));
        req.on("end", () => {
          received = { url: req.url, body: raw };
          res.writeHead(200, { "Content-Type": "application/json" });
          res.end(JSON.stringify({ nodes: [{ id: "a", x: 1, y: 2 }], layoutMillis: 7 }));
        });
      });
      await new Promise<void>((resolve) => upstream.listen(0, resolve));
      target = `http://127.0.0.1:${(upstream.address() as AddressInfo).port}`;
    });

    afterAll(async () => {
      await new Promise<void>((resolve) => upstream.close(() => resolve()));
    });

    it("forwards the body to /layout and relays the response", async () => {
      const reqBody = { options: {}, nodes: [{ id: "a", partition: 1 }], edges: [] };
      const res = await request(createApp({ layoutServiceUrl: target }))
        .post("/api/layout")
        .set("Content-Type", "application/json")
        .send(reqBody);

      expect(res.status).toBe(200);
      expect(res.body).toEqual({ nodes: [{ id: "a", x: 1, y: 2 }], layoutMillis: 7 });
      expect(received.url).toBe("/layout");
      expect(JSON.parse(received.body!)).toEqual(reqBody);
    });
  });

  it("502s when the upstream is unreachable", async () => {
    // Port 1 is unbound; the connection refuses immediately.
    const res = await request(createApp({ layoutServiceUrl: "http://127.0.0.1:1" }))
      .post("/api/layout")
      .set("Content-Type", "application/json")
      .send({ options: {}, nodes: [], edges: [] });
    expect(res.status).toBe(502);
    expect(res.body.error).toMatch(/unreachable/);
  });
});
