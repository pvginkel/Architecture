# CLAUDE.md

Project context for Claude Code agents working in this repo.

## What this repo is

The architecture diagram viewer for [webathome.org](https://webathome.org). React + ReactFlow + ELK, built with Vite, served by nginx from a single container at `architecture.webathome.org/viewer/`, embedded back into webathome.org as an iframe. This repo will grow into a federated architecture system — see `docs/architecture-rebuild/` for the full multi-phase plan.

## About the user

Pieter van Ginkel — Domain Architect at IVO Rechtspraak (Dutch judiciary IT), professional software developer since 2001. Skip beginner framing. Communicate architecture and design tradeoffs directly.

## Deployment context

Mature self-hosted stack: Kubernetes, Jenkins, Kaniko, Ansible. Don't suggest hosting alternatives. Don't redesign CI/CD. Focus on the container artifact (Dockerfile, image contents, what it exposes); the K8s/Jenkins glue is the user's.

## Working style

- Commit yourself, regularly, in clear chunks. Not only at the end. One commit per meaningful unit of work is the norm.
- Maintenance ergonomics are not a priority. Hand-editing data files is fine.
- The user is comfortable with a wide tech stack.
