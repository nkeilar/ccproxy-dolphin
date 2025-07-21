# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Grok-Anthropic Proxy Server - a Flask-based API proxy that translates Anthropic Claude API requests to xAI's Grok API format. It allows Claude-compatible applications to use Grok models by acting as a transparent proxy.

## Architecture

The proxy operates as a simple request translator:
- Listens on port 8000 for Claude API requests at `/v1/messages`
- Translates Claude model names to Grok equivalents
- Forwards requests to xAI's API at `https://api.x.ai/v1/chat/completions`
- Returns responses in Claude-compatible format

Model mappings:
- `claude-3-5-sonnet-20241022` → `grok-4`
- `claude-3-haiku-20240307` → `grok-4`

## Development Commands

### Running the Server
```bash
# Set the xAI API key
export XAI_API_KEY="your-xai-api-key"

# Install dependencies
pip install flask requests

# Run the server
python grok_proxy.py
```

### Testing the Proxy
```bash
# Test with curl (replace with your actual API key)
curl -X POST http://localhost:8000/v1/messages \
  -H "Content-Type: application/json" \
  -H "x-api-key: dummy-key" \
  -d '{
    "model": "claude-3-haiku-20240307",
    "messages": [{"role": "user", "content": "Hello"}],
    "max_tokens": 100
  }'
```

## Key Implementation Details

The main logic resides in `grok_proxy.py`:
- Single Flask route handler at `/v1/messages`
- Handles both streaming and non-streaming responses
- Uses environment variable `XAI_API_KEY` for authentication with xAI
- Currently runs in debug mode on all interfaces (0.0.0.0:8000)

## Common Tasks

### Adding New Model Mappings
Model mappings are hardcoded in the `messages()` function. To add new mappings, modify the conditional logic that translates `data['model']`.

### Implementing Error Handling
Currently, the proxy has minimal error handling. When implementing, focus on:
- API connection failures
- Invalid API keys
- Rate limiting responses
- Malformed requests

### Creating a Requirements File
Create `requirements.txt` with:
```
flask
requests
```

## Important Considerations

1. The proxy currently runs in debug mode - disable this for production use
2. No request validation is performed - the proxy forwards requests as-is
3. Authentication is handled via environment variable only
4. Streaming responses are passed through transparently
5. The proxy only implements the `/v1/messages` endpoint