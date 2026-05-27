# Multi-stage build for the Architecture validation service.
#
# Stages:
#   1. check-schemas — runs `generate.py --check` to fail the build if the
#      committed schema/v0.1/generated/ tree is out of sync with subset.yaml
#      and the vendored ArchiMate sources.
#   2. build-viewer  — npm + vite build of viewer/.
#   3. build-service — npm + tsc build of service/.
#   4. (final)       — node:20-alpine runtime carrying the built service,
#                      viewer-dist, schema tree, USAGE.md, and a placeholder
#                      data/ that v3's collector will populate at pipeline
#                      time.

# ---- stage 1: schema sanity ----
FROM python:3.13-slim AS check-schemas
WORKDIR /work
RUN pip install --no-cache-dir poetry==1.8.5
COPY tooling/pyproject.toml tooling/poetry.lock ./tooling/
RUN cd tooling && poetry install --no-root --only main
COPY schema/ ./schema/
COPY tooling/ ./tooling/
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

# ---- final runtime ----
FROM node:20-alpine
WORKDIR /app

COPY --from=build-service /app/dist        ./dist
COPY --from=build-service /app/node_modules ./node_modules
COPY --from=build-viewer  /app/dist        ./viewer-dist
COPY --from=check-schemas /work/schema     ./schema
COPY USAGE.md                              ./USAGE.md

# Placeholder for the merged dataset. v3 (docs/architecture-rebuild/
# 05-collector-and-pipeline.md) replaces this RUN with `COPY dist/data
# ./data` once the Jenkinsfile runs tooling/collect.py before kaniko.
RUN mkdir -p ./data/v0.1

ENV NODE_ENV=production
ENV PORT=8080
EXPOSE 8080

ENTRYPOINT ["node", "dist/index.js"]
