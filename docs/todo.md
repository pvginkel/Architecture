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

## Service↔interface: two valid idioms across producers

The published dataset now expresses "a service is reachable at an endpoint" two different (both ArchiMate-3.2-valid) ways:

- Ansible uses `TechnologyInterface --Assignment--> TechnologyService` (the endpoint exposes the service) — ×18.
- The `architecture` self-producer (`docs/architecture/home-automation.yaml`) uses `SystemSoftware --Composition--> TechnologyInterface` (the daemon owns the endpoint) — ×1.

Both are legal and both validate, but they're structurally different shapes, so the viewer would wire service/interface relationships inconsistently across producers. The manual's "common mappings" table currently blesses only the Assignment idiom (`An interface exposes a service`). The `ss → if Composition` form was a deliberate choice to express daemon-owns-endpoint, which the Assignment idiom drops.

Decide on one canonical idiom (or explicitly allow both with a documented meaning), update the producer manual, and reconcile the one home-automation relation. Not urgent — no live breakage — but worth settling before the viewer renders the technology layer or before more producers introduce services/interfaces.

Revisit when: the viewer starts rendering service/interface wiring, or a third producer adds technology services.
