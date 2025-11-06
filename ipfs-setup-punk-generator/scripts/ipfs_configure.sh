#!/usr/bin/env bash
set -euo pipefail

compose="docker compose"

# Configure addresses
$compose exec -T ipfs ipfs config Addresses.API /ip4/127.0.0.1/tcp/5001
$compose exec -T ipfs ipfs config Addresses.Gateway /ip4/0.0.0.0/tcp/8080

# Apply 'server' profile (safe defaults for servers)
$compose exec -T ipfs ipfs config profile apply server || true

echo "Configured IPFS addresses."
echo "API:     http://127.0.0.1:5001   (local only)"
echo "Gateway: http://0.0.0.0:8080     (public via nginx recommended)"
