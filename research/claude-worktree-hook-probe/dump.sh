#!/bin/bash
# Records what a hook process sees: its PWD, CLAUDE_PROJECT_DIR, and the payload cwd.
p=$(cat)
ev=$(printf '%s' "$p" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("hook_event_name"), "| payload.cwd=", d.get("cwd"), "| source=", d.get("source",""))')
echo "$ev | PWD=$PWD | CLAUDE_PROJECT_DIR=${CLAUDE_PROJECT_DIR:-<unset>}" >> "$PROBE_LOG"
