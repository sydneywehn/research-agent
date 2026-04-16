#!/bin/bash
INPUT=$(cat)
PROMPT=$(echo "$INPUT" | jq -r '.prompt // empty')
if [ -n "$PROMPT" ]; then
  TS=$(date '+%Y-%m-%d %H:%M:%S')
  printf "## [%s] User\n\n%s\n\n---\n\n" "$TS" "$PROMPT" >> /Users/sydneywehn/research-agent/prompt-log.md
fi
