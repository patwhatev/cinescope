#!/bin/bash
# Start the self-hosted Dailies server. ctrl-C to stop.
#   ./serve.sh            localhost:8420
#   ./serve.sh --lan      also reachable from other devices on your network
cd "$(dirname "$0")"
exec python3 pipeline/serve.py "$@"
