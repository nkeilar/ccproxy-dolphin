# Grok-Anthropic Proxy

A Flask-based API proxy that translates Anthropic Claude API requests to xAI's Grok API format, allowing Claude-compatible applications to use Grok models.

## Features

- Translates Anthropic `/v1/messages` requests to OpenAI `/v1/chat/completions` format
- Supports both streaming and non-streaming responses
- Comprehensive request/response logging
- Customizable system prompts with dynamic content preservation
- Configuration-based prompt transformation (remove Claude/Anthropic references)
- Tool calling support (function calling)
- Configurable model mappings

## Prerequisites

- Python 3.10+
- An xAI API key (get one from https://console.x.ai/)
- Claude Code installed (`pip install claude-code`)

## Quick Start

### 1. Clone and Set Up

```bash
git clone <this-repo>
cd grok-anthropic

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install flask requests
```

### 2. Set Your xAI API Key

```bash
export XAI_API_KEY="your-xai-api-key-here"  # On Windows: use 'set' instead of 'export'
```

### 3. Start the Proxy

```bash
python grok_proxy_openai.py
```

The proxy will start on `http://localhost:8000`. Keep this terminal open.

### 4. Configure Claude Code

In a new terminal:

```bash
# Tell Claude Code to use our proxy
export ANTHROPIC_BASE_URL=http://localhost:8000
export ANTHROPIC_API_KEY=dummy-key  # Can be anything, proxy uses XAI_API_KEY

# On Windows:
# set ANTHROPIC_BASE_URL=http://localhost:8000
# set ANTHROPIC_API_KEY=dummy-key
```

### 5. Launch Claude Code

```bash
claude
```

Now Claude Code will use Grok 4 for all requests!

## Model Mapping

The proxy automatically maps these Claude models to Grok 4:
- `claude-3-5-sonnet-20241022` → `grok-4`
- `claude-3-haiku-20240307` → `grok-4`

Add more mappings in `grok_proxy.py` if needed.

## Testing

Test the proxy directly:

```bash
curl -X POST http://localhost:8000/v1/messages \
  -H "Content-Type: application/json" \
  -H "x-api-key: dummy-key" \
  -d '{
    "model": "claude-3-haiku-20240307",
    "messages": [{"role": "user", "content": "Hello"}],
    "max_tokens": 100
  }'
```

## Custom System Prompts

The proxy supports customizing system prompts while preserving dynamic content like environment information and model details.

### Basic Usage

Enable custom prompts by setting environment variables:

```bash
export USE_CUSTOM_PROMPT=true
export CUSTOM_PROMPT_FILE=system_prompt_template_unrestricted.txt
export PROMPT_CONFIG_FILE=prompt_config.json
```

### Configuration File

Create a `prompt_config.json` to control prompt transformations:

```json
{
  "system_name": "Advanced AI Coding Agent",
  "model_name_override": "Grok-4",
  "remove_claude_references": true,
  "remove_anthropic_references": true,
  "remove_defensive_restrictions": true,
  "custom_help_info": {
    "help_command": "/help",
    "feedback_url": null,
    "documentation_url": null
  }
}
```

### Custom Prompt Template

The template file supports placeholders that get filled with dynamic content:
- `{{ENV_INFO}}` - Environment information (OS, working directory, etc.)
- `{{MODEL_INFO}}` - Model name and version
- `{{MCP_INSTRUCTIONS}}` - MCP server instructions if available

Example template structure:
```
You are an advanced AI coding assistant.

{{ENV_INFO}}

{{MODEL_INFO}}

# Your custom instructions here...

{{MCP_INSTRUCTIONS}}
```

## Troubleshooting

### "Connection refused" error
- Make sure the proxy is running (`python grok_proxy_openai.py`)
- Check that port 8000 is not in use by another process

### "XAI_API_KEY environment variable is not set!"
- Set your xAI API key: `export XAI_API_KEY="your-key"`

### "Argument not supported: cache_control"
- This is already handled by the proxy, but if you see other unsupported parameters, add them to the removal list in `proxy_messages()`

### Rate limits or API errors
- Check your xAI account limits at https://console.x.ai/
- The proxy passes through all xAI error messages for debugging

## Security Notes

- **Local use only**: The proxy runs without authentication. Don't expose port 8000 publicly.
- **API key security**: Your xAI API key is only stored in the environment variable, never logged.
- **Debug mode**: Disable `debug=True` in production for security.

## Costs

This uses your xAI API credits. Monitor usage at https://console.x.ai/

## Contributing

Feel free to submit issues or PRs for:
- Additional model mappings
- Better error handling
- Support for more Anthropic API endpoints
- Performance improvements