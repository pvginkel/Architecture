# todo

Deferred decisions captured during v0. Revisit when each phase becomes relevant.

## Logos: dedupe vs. page-load performance

For v0 the logos in `viewer/public/logos/` are a duplicate of webathome.org's `public/logos/`. A single-source-of-truth (e.g., serving logos from `architecture.webathome.org/logos/` and having webathome.org's ticker reference them cross-origin) is tempting but costs an extra TLS handshake on first paint of the ticker. Cross-origin caching, preconnect hints, and CDN behavior all need to be measured before committing. Until then, duplication is fine.

Revisit when: someone adds or removes a logo and has to remember to keep both repos in sync. The pain of duplication should drive the dedupe decision, not theoretical purity.

## Logos: producer-supplied logos in the build artifact

Today the viewer reads logos from `viewer/public/logos/` at build time and they end up baked into the nginx image. Once federated producers (later phases — see `docs/architecture-rebuild/04-producer-protocol.md` and `05-collector-and-pipeline.md`) start contributing nodes, their logos will not live in this repo. Need a story for how producer-supplied logos land in the container image:

- Ingestion at build time (collector pulls them and the Dockerfile copies them in)?
- Sidecar volume mounted by K8s?
- Signed bundles fetched at runtime?

Decide before federation lands.
