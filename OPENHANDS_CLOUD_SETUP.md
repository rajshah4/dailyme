# OpenHands Cloud LLM Integration - Setup Guide

## Summary

The DailyMe pipeline now uses **OpenHands Cloud LLM API** for story extraction from newsletters. This guide explains the two types of API keys and how to configure the pipeline.

## ✅ What Works

The pipeline successfully uses OpenHands LLM API through the `openhands/` model prefix, which automatically routes requests to the OpenHands LiteLLM proxy at `https://llm-proxy.app.all-hands.dev/`.

**Test Results:**
- ✅ LLM API key authentication working
- ✅ Direct LLM completions via `llm.completion()` 
- ✅ Story extraction from newsletters
- ✅ Pipeline runs successfully

## 🔑 Two Types of API Keys

OpenHands Cloud provides **two separate API keys**:

### 1. Cloud API Key (for starting agent conversations)
- Format: `sk-oh-...`
- Used for: Starting agent jobs via REST API
- Get it from: Account settings
- **NOT used for direct LLM access**

### 2. LLM API Key (for direct LLM access)
- Format: `sk-...` (shorter)
- Used for: Direct LLM completions in your code
- Get it from: Settings > API Keys tab > "LLM API Key"
- **This is what the DailyMe pipeline needs**

## 📋 Configuration

### 1. Get Your OpenHands LLM API Key

1. Log in to [OpenHands Cloud](https://app.all-hands.dev)
2. Go to **Settings**
3. Navigate to the **API Keys** tab
4. Copy your **LLM API Key** (not the Cloud API key)

### 2. Configure .env File

Create or update `.env` in the project root:

```bash
# DailyMe Pipeline - OpenHands Cloud Configuration
DATABASE_URL=postgresql+asyncpg://your-neon-connection-string
GMAIL_TOKEN_JSON=your-gmail-token-json

# OpenHands LLM API Key (for direct LLM access)
LLM_MODEL=openhands/claude-sonnet-4-5-20250929
LLM_API_KEY=your-llm-api-key-here

LLM_TIMEOUT=120
LLM_NUM_RETRIES=2
```

**Important:** Use the `openhands/` prefix in `LLM_MODEL`. This tells the SDK to route through the OpenHands LiteLLM proxy.

### 3. Run the Pipeline

```bash
# Install dependencies
uv sync --extra pipeline

# Run the full pipeline
uv run python scripts/run_pipeline.py

# Or reprocess a specific email
uv run python reprocess_email.py <gmail_id>
```

## 🏗️ How It Works

1. **LLM Initialization**: `app/processing/llm_extract.py` calls `LLM.load_from_env()`
2. **Model Prefix**: The `openhands/` prefix auto-configures the base URL to `https://llm-proxy.app.all-hands.dev/`
3. **Authentication**: The LLM API key is sent with each request
4. **Story Extraction**: The LLM receives newsletter HTML and returns structured JSON with stories

## 💰 Pricing

OpenHands LLM API follows official provider rates with no markup:

| Model | Input (per 1M tokens) | Output (per 1M tokens) |
|-------|----------------------|------------------------|
| claude-sonnet-4-5-20250929 | $3.00 | $15.00 |

**Typical newsletter:** ~5,000 tokens → ~$0.015-0.075 per email

## 🔧 Code Structure

```
app/processing/llm_extract.py
├── _get_llm()              # Initializes LLM from environment
├── is_configured()         # Checks if LLM is available
└── extract_stories()       # Extracts stories using LLM completion
```

## 📝 Example Usage

```python
from openhands.sdk import LLM
from openhands.sdk.llm import Message, TextContent
from dotenv import load_dotenv

load_dotenv()

# Load LLM from environment
llm = LLM.load_from_env()

# Make a completion request
response = llm.completion(
    messages=[Message(
        role="user",
        content=[TextContent(text="Extract stories from this newsletter...")]
    )]
)

print(response.message.content[0].text)
```

## ✅ Success Confirmation

Test that your LLM API key works:

```bash
cd dailyme
python3 -c "
from dotenv import load_dotenv
load_dotenv()

from openhands.sdk import LLM
from openhands.sdk.llm import Message, TextContent

llm = LLM.load_from_env()
print(f'✓ LLM loaded: {llm.model}')

response = llm.completion(
    messages=[Message(role='user', content=[TextContent(text='Say hello!')])]
)
print(f'✓ Response: {response.message.content[0].text}')
"
```

Expected output:
```
✓ LLM loaded: litellm_proxy/claude-sonnet-4-5-20250929
✓ Response: Hello!
```

## 🚀 Next Steps

1. ✅ Get your OpenHands LLM API key from the dashboard
2. ✅ Update `.env` with the LLM API key
3. ✅ Run the pipeline: `uv run python scripts/run_pipeline.py`
4. ✅ Monitor LLM extraction in the logs

## 📚 Resources

- [OpenHands Cloud](https://app.all-hands.dev)
- [OpenHands LLM Documentation](https://docs.openhands.dev/openhands/usage/llms/openhands-llms)
- [OpenHands SDK Guide](https://docs.openhands.dev/sdk)
- [LiteLLM Documentation](https://docs.litellm.ai/)

---

**Committed:** 2026-03-05  
**Status:** ✅ Working with OpenHands LLM API key
