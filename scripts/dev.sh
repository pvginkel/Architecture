#!/usr/bin/env bash
# Vite dev server for the viewer, at https://viewer.<env-id>.home/viewer/.
#
# Runs in the modern-app tool sidecar: the dev container carries a node, but the
# viewer's node_modules are installed by `kc project setup` inside that sidecar,
# so the dev server has to run where they were built.
set -euo pipefail
cd "$(dirname "$0")/../viewer"
exec cexec modern-app npm run dev -- "$@"
