#!/bin/bash
# This script sets up environment variables for OpenHands Cloud to run the pipeline.
# It should be sourced by the OpenHands agent before running the pipeline.
#
# Usage in OpenHands conversation:
#   source .github/workflows/openhands-env-setup.sh && uv run python scripts/run_pipeline.py

# These will be passed from GitHub secrets to the OpenHands trigger
# and should be available as environment variables when the agent runs

if [ -z "$DATABASE_URL" ]; then
    echo "⚠️  Warning: DATABASE_URL not set"
    echo "The pipeline needs DATABASE_URL to connect to Neon Postgres"
fi

if [ -z "$GMAIL_TOKEN_JSON" ]; then
    echo "⚠️  Warning: GMAIL_TOKEN_JSON not set"
    echo "The pipeline needs GMAIL_TOKEN_JSON to fetch newsletters"
fi

if [ -z "$LLM_MODEL" ]; then
    export LLM_MODEL="openhands/claude-sonnet-4-5-20250929"
    echo "ℹ️  Using default LLM_MODEL: $LLM_MODEL"
fi

# Set timeouts for LLM calls
export LLM_TIMEOUT="${LLM_TIMEOUT:-120}"
export LLM_NUM_RETRIES="${LLM_NUM_RETRIES:-2}"

echo "✅ Environment configured for pipeline"
echo "   DATABASE_URL: ${DATABASE_URL:0:30}..."
echo "   LLM_MODEL: $LLM_MODEL"
echo "   LLM_TIMEOUT: $LLM_TIMEOUT"
echo "   LLM_NUM_RETRIES: $LLM_NUM_RETRIES"
