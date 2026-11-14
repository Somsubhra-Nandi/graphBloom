#!/usr/bin/env bash
# Start a single-node local HydraDB from the official image. Data persists in .hydradb/.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p .hydradb/store .hydradb/cache
[ -f .hydradb/auth-token ] || printf '%s\n' 'local-development-token-32-bytes' > .hydradb/auth-token
docker rm -f hydradb >/dev/null 2>&1 || true
docker run -d --name hydradb -p 7687:7687 -p 8443:8443 -p 9090:9090 \
  -v "$PWD/.hydradb:/data" \
  -e CLOUD_PROVIDER=local -e LOCAL_PATH=/data/store \
  -e GRAPH_NAMESPACE=default -e GRAPH_ID=default -e GRAPH_CELL_ID=cell-0 -e GRAPH_CELLS=cell-0 \
  -e GRAPH_NODE_ID=node-0 -e GRAPH_BOLT_NODE_ADDRESSES=node-0=127.0.0.1:7687 \
  -e GRAPH_ADVERTISED_BOLT_ADDR=127.0.0.1:7687 -e GRAPH_DATA_CACHE_DIR=/data/cache \
  -e GRAPH_AUTH_TOKEN_FILE=/data/auth-token -e GRAPH_ALLOW_PLAINTEXT=true \
  -e GRAPH_USAGE_REPORT_ENABLED=false -e RUST_MIN_STACK=33554432 \
  ghcr.io/hydra-db/hydradb:0.4.0
