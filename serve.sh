#!/bin/bash
# Start the self-hosted Dailies server. ctrl-C to stop.
cd "$(dirname "$0")"
exec python3 pipeline/serve.py "$@"
