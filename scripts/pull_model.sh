#!/usr/bin/env bash
# scripts/pull_model.sh — pull a model into the running crew-chief service.
#
# Usage:
#   scripts/pull_model.sh [MODEL]
#
# MODEL defaults to llama3.2 when not provided.
set -euo pipefail

MODEL="${1:-llama3.2}"
PORT="${CREW_CHIEF_PORT:-11434}"
BASE_URL="http://localhost:${PORT}"

echo "Pulling model: $MODEL ..."
curl -sf "${BASE_URL}/api/pull" \
    -H "Content-Type: application/json" \
    -d "{\"name\": \"${MODEL}\"}"

echo ""
echo "Model pull complete: $MODEL"
