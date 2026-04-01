#!/usr/bin/env bash
# PreToolUse hook: guard destructive terminal commands.
# Blocks rm -rf, DROP TABLE, docker system prune without user confirmation.
set -euo pipefail

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('toolName',''))" 2>/dev/null || echo "")

if [ "$TOOL_NAME" != "run_in_terminal" ]; then
  echo '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"allow"}}'
  exit 0
fi

COMMAND=$(echo "$INPUT" | python3 -c "
import sys, json
params = json.load(sys.stdin).get('toolInput', {})
print(params.get('command', ''))
" 2>/dev/null || echo "")

# Check for destructive patterns
if echo "$COMMAND" | grep -qiE '(rm\s+-rf\s+/|DROP\s+TABLE|DROP\s+DATABASE|docker\s+system\s+prune|git\s+push\s+--force|git\s+reset\s+--hard)'; then
  echo "{\"hookSpecificOutput\":{\"hookEventName\":\"PreToolUse\",\"permissionDecision\":\"ask\",\"permissionDecisionReason\":\"Destructive command detected: $COMMAND\"}}"
  exit 0
fi

echo '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"allow"}}'
exit 0
