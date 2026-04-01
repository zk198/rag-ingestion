#!/usr/bin/env bash
# PostToolUse hook: run pytest after source edits to catch regressions early.
# Receives JSON on stdin with tool name and parameters.
set -euo pipefail

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('toolName',''))" 2>/dev/null || echo "")

# Only trigger after file-editing tools
case "$TOOL_NAME" in
  replace_string_in_file|create_file|edit_notebook_file|multi_replace_string_in_file)
    ;;
  *)
    echo '{"decision":"continue"}'
    exit 0
    ;;
esac

# Only if tests directory exists
if [ ! -d "tests" ]; then
  echo '{"decision":"continue"}'
  exit 0
fi

# Run tests — non-blocking on failure (exit 0 with a warning message)
if docker run --rm -v "./tests:/app/tests" pst-agent:latest bash -c "pip install pytest -q 2>/dev/null && python -m pytest /app/tests/ -q --tb=short" 2>&1; then
  echo '{"decision":"continue","systemMessage":"All tests passed."}'
else
  echo '{"decision":"continue","systemMessage":"WARNING: Some tests failed after this edit. Review test output above."}'
fi

exit 0
