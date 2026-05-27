# CLAUDE.md

Project context for Claude Code agents working in this repo.

## What this repo is

The architecture diagram viewer for [webathome.org](https://webathome.org). React + ReactFlow + ELK, built with Vite, served by nginx from a single container at `architecture.webathome.org/viewer/`, embedded back into webathome.org as an iframe. This repo will grow into a federated architecture system — see `docs/architecture-rebuild/` for the full multi-phase plan.

**This repo is public.** Do not commit secrets, credentials, internal hostnames/IPs, employee names beyond what's already public, or any other security-sensitive information. Assume everything written here is world-readable.

## About the user

Pieter van Ginkel — Domain Architect at IVO Rechtspraak (Dutch judiciary IT), professional software developer since 2001. Skip beginner framing. Communicate architecture and design tradeoffs directly.

## Deployment context

Mature self-hosted stack: Kubernetes, Jenkins, Kaniko, Ansible. Don't suggest hosting alternatives. Don't redesign CI/CD. Focus on the container artifact (Dockerfile, image contents, what it exposes); the K8s/Jenkins glue is the user's.

## Working style

- Commit your own work, without being asked, as soon as a meaningful unit is done. Don't wait until the end of the session, and don't wait for the user to ask. Even a one-line change to CLAUDE.md is its own commit.
- Maintenance ergonomics are not a priority. Hand-editing data files is fine.
- The user is comfortable with a wide tech stack.

## No defensive coding. No "just in case" infrastructure.

Two related allergies, both load-bearing. Either kind of padding is a defect on the same level as a missing test.

- **Fail loudly when things break.** No try/except that swallows errors. No "drop the bad producer, continue with the rest" patterns. No null-guards or defaulted-empty-collections for conditions the framework already prevents. Validation at boundaries (schema, user input, external API) is the *point*, not defensive coding.
- **Don't add safety nets nothing breaks without.** No scheduled rebuilds or periodic refreshes "as a hedge against missed triggers" unless the missing-triggers case is known to happen. No retries layered on operations expected to succeed once. No fallback caches, staleness windows, or last-known-good layers unless addressing a real observed failure. No belt-and-suspenders double-checks at adjacent layers. No graceful-degradation paths that fall back to the previous version of the code.

Before adding any hedge: *what concrete failure does this catch that the existing path doesn't?* "Nothing specific, but just in case" / "the spec doc suggested it would be nice" — don't add it. Spec docs that carry forward "would be nice" hedges don't override this rule; push back at design time rather than echoing them.

Would the failure be obvious now, or silently corrupt the system later? Pick obvious-now.
