#!/usr/bin/env bash
set -euo pipefail

mode="${1:-api}"
shift || true

case "$mode" in
  api)
    exec python -m pst_agent.api "$@"
    ;;
  mcp)
    exec python -m pst_agent.mcp_server "$@"
    ;;
  cli)
    exec pst-agent "$@"
    ;;
  bash)
    exec bash "$@"
    ;;
  *)
    exec "$mode" "$@"
    ;;
esac
