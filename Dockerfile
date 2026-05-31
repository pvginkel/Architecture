# Multi-stage build for the Architecture validation service.
#
# Stages:
#   1. check-schemas  — runs `generate.py --check` to fail the build if the
#      committed schema/v0.1/generated/ tree is out of sync with subset.yaml
#      and the vendored ArchiMate sources.
#   2. build-viewer   — npm + vite build of viewer/.
#   3. build-service  — npm + tsc build of service/.
#   4. run-collector  — runs tooling/collect.py against producer-artifacts/
#      copied in from the build context, emitting dist/data/v0.1/.
#   5. (final)        — node:20-alpine runtime carrying the built service,
#                       viewer-dist, schema tree, USAGE.md, and the merged
#                       dataset COPY'd from the run-collector stage.
#
# producer-artifacts/ is .dockerignore'd from local `docker build` so a
# developer can't accidentally bundle local fixtures into a production
# image. The Jenkinsfile (v3 #13) opts the pipeline in by populating the
# directory via copyArtifacts and clearing the .dockerignore exclusion
# before kaniko runs.

# ---- stage 1: schema sanity ----
FROM python:3.13-slim AS check-schemas
WORKDIR /work
RUN pip install --no-cache-dir poetry
COPY tooling/pyproject.toml tooling/poetry.lock ./tooling/
RUN cd tooling && poetry install --no-root --without dev
# Copy the whole context (poetry deps are already layered above off
# pyproject/poetry.lock). generate.py and collect.py read from schema/,
# tooling/, viewer/, views/, pipeline-producers.yaml and producer-artifacts/;
# a blanket copy keeps the build from breaking each time the tooling reaches
# into a new path. node_modules/.git/dist stay out via .dockerignore, which CI
# strips only the producer-artifacts/ entry from.
COPY . .
RUN cd tooling && poetry run python generate.py --check

# ---- stage 2: viewer ----
FROM node:20-alpine AS build-viewer
WORKDIR /app
COPY viewer/package*.json ./
RUN npm ci
COPY viewer/ ./
RUN npm run build

# ---- stage 3: service ----
FROM node:20-alpine AS build-service
WORKDIR /app
COPY service/package*.json ./
RUN npm ci
COPY service/ ./
RUN npm run build

# ---- stage 4: federation collector ----
# Reuses the schema-validated Poetry environment from check-schemas. Reads
# every registered producer's <id>/architecture.yaml from producer-artifacts/
# in the build context, validates + merges + cross-checks, writes the merged
# dataset to /work/dist/data/v0.1/. Fails the build on any collector error.
#
# --relaxed tolerates dangling cross-producer refs while the federation is
# still onboarding (apps whose owning producer isn't emitting yet). This must
# match the Jenkinsfile's preview "Run collector" stage — the two runs are
# byte-identical only when given the same flags. Drop --relaxed from both once
# every referenced producer is online so dangling refs fail the build again.
FROM check-schemas AS run-collector
WORKDIR /work
# pipeline-producers.yaml, views/ and producer-artifacts/ already arrived with
# the check-schemas COPY . . above.
RUN cd tooling && poetry run python collect.py \
      --producers /work/pipeline-producers.yaml \
      --in /work/producer-artifacts \
      --out /work/dist \
      --relaxed

# ---- final runtime ----
FROM node:20-alpine
WORKDIR /app

COPY --from=build-service  /app/dist          ./dist
COPY --from=build-service  /app/node_modules  ./node_modules
COPY --from=build-viewer   /app/dist          ./viewer-dist
COPY --from=check-schemas  /work/schema       ./schema
COPY --from=run-collector  /work/dist/data    ./data
COPY USAGE.md                                 ./USAGE.md

ENV NODE_ENV=production
ENV PORT=8080
EXPOSE 8080

ENTRYPOINT ["node", "dist/index.js"]
