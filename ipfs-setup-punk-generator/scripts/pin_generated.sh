#!/usr/bin/env bash
set -euo pipefail

DIR="${1:-generated}"

if [ ! -d "$DIR" ]; then
  echo "Directory '$DIR' not found. Run your generator first (it should create ./generated)."
  exit 1
fi

compose="docker compose"

ROOT_CID=$($compose exec -T ipfs ipfs add -Qr "$DIR")
echo "Root CID: $ROOT_CID"

$compose exec -T ipfs ipfs pin add "$ROOT_CID" >/dev/null || true
mkdir -p CIDs
ts=$(date -u +"%Y%m%dT%H%M%SZ")
echo "$ROOT_CID" > "CIDs/${ts}_${DIR//\//_}.cid"

GATEWAY_PORT=${IPFS_GATEWAY_PORT:-8080}
GATEWAY_DOMAIN=${GATEWAY_DOMAIN:-}

HOST_IP=$(hostname -I | awk '{print $1}')
echo ""
echo "ipfs://$ROOT_CID"
echo "Local gateway:   http://127.0.0.1:${GATEWAY_PORT}/ipfs/${ROOT_CID}"
echo "Host gateway:    http://${HOST_IP}:${GATEWAY_PORT}/ipfs/${ROOT_CID}"
if [ -n "$GATEWAY_DOMAIN" ] && [ "$GATEWAY_DOMAIN" != "gateway.example.com" ]; then
  echo "Public gateway:  https://${GATEWAY_DOMAIN}/ipfs/${ROOT_CID}"
fi
