#!/bin/sh
# Run: ./launch-agent.sh
CDPATH= cd -P "$(dirname "$0")" || exit 1
export LUMINARY_REQUEST_TIMEOUT_S=60
exec uv run --extra agent luminary fly --policy llm --provider ollama --model llama3.2:3b --base-url http://127.0.0.1:11434 --tier 1
