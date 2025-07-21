# xAI Grok Proxy - Tool Format Investigation

## Goal
Create a proxy that allows Claude Code to use xAI's Grok-4 model by translating between Anthropic and xAI API formats.

## Current Status
- Basic chat functionality works (after removing tools)
- Tool/function calling has critical issues with specific property names

## What We've Learned

### 1. Basic Parameter Issues (SOLVED)
- **cache_control**: Not supported by xAI, must be removed from:
  - Top-level request data
  - Individual messages
  - Message content items
  - System messages

### 2. Model Mapping (SOLVED)
- Map all Claude models to `grok-4`
- Works for basic chat

### 3. Tools Format Investigation (PARTIALLY SOLVED)

#### Key Discovery: xAI Uses Anthropic Format
Through systematic testing, we discovered:
- xAI expects Anthropic format with `name`, `description`, and `input_schema`
- OpenAI format (with `type: "function"`) is NOT supported
- Must remove `$schema` and `additionalProperties` from schemas

#### Critical Issue: Reserved Property Names (CONFIRMED)
**The property name `description` in input_schema causes "Invalid function schema" error!**

Testing revealed (2025-07-20 - empirically verified):
- ✅ Working property names: `input`, `text`, `query`, `prompt`, `message`, `content`, `value`, `data`, `parameter`, `arg`, `desc`, `task_prompt`, `user_prompt`, `instruction`
- ❌ Failing property name: `description` (when used as a property in input_schema) 
- ✅ `prompt` works fine as a property name (WebFetch tool works with it)
- ✅ Using `description` at the tool level (not in properties) works fine

Example of the issue:
```json
{
  "name": "Task",
  "description": "This is fine",  // ✅ OK at tool level
  "input_schema": {
    "type": "object",
    "properties": {
      "description": {"type": "string"}  // ❌ FAILS - reserved word
    }
  }
}
```

#### What We've Tried:

**Successful Format (without reserved words):**
```json
{
  "name": "add",
  "description": "Add two numbers",
  "input_schema": {
    "type": "object",
    "properties": {
      "a": {"type": "number"},
      "b": {"type": "number"}
    },
    "required": ["a", "b"]
  }
}
```

**Failed Attempts:**
1. OpenAI format with `type: "function"` wrapper - doesn't work
2. Using `parameters` instead of `input_schema` - doesn't work
3. Having `description` as a property name - causes failure

### 4. tool_choice Parameter Issues (SOLVED)
- Must be removed entirely - xAI doesn't support it in the expected format

## Current Implementation (WORKING! 🎉)

The proxy now successfully works with Claude Code! Here's the final solution:

### Working Features
1. ✅ **Basic chat** - All prompts work perfectly
2. ✅ **Tool calling** - Most Claude Code tools work (Read, Write, Edit, MultiEdit, LS, TodoWrite, WebSearch, etc.)
3. ✅ **Proper filtering** - Automatically skips incompatible tools
4. ✅ **No MCP needed** - Use `--mcp-config "" --strict-mcp-config` to disable MCP servers

### Implementation Details
1. Removes all `cache_control` parameters (from all levels)
2. Removes `$schema` and `additionalProperties` from tool schemas
3. Filters out specific problematic tools:
   - Tools with `description` or `prompt` as property names (Task, Bash, WebFetch)
   - Glob and Grep tools (have other compatibility issues)
4. Removes `tool_choice` parameter
5. Maps all models to `grok-4`

### Usage
```bash
# Set environment variables
export ANTHROPIC_BASE_URL=http://localhost:8000
export ANTHROPIC_API_KEY=anything  # xAI key is in the proxy

# Run Claude Code without MCP servers
claude --mcp-config "" --strict-mcp-config -p "your prompt"
```

### What Changed (2025-07-20 Final)
- **Discovered** that without MCP servers, only 15 core tools are sent (instead of 102)
- **Found** that Glob and Grep tools cause issues even without problematic property names
- **Confirmed** tool calling works - successfully tested Read tool
- **Result**: Functional Claude Code with xAI Grok backend!

## Update: OpenAI Format Approach (2025-07-20)
- **Discovered** xAI supports both Anthropic (`/v1/messages`) and OpenAI (`/v1/chat/completions`) endpoints
- **Implemented** CCProxy's approach: Convert Anthropic → OpenAI → send to xAI → convert back
- **Success** with non-streaming requests and tool calling
- **Issue**: Streaming responses need format conversion (OpenAI SSE → Anthropic SSE)

## Tools Compatibility Summary

### Working Tools ✅
- Read, Write, Edit, MultiEdit
- LS, TodoWrite, WebSearch
- NotebookRead, NotebookEdit
- exit_plan_mode

### Problematic Tools ❌
- **Task** - has `description` property (confirmed causes error)
- **Bash** - has `description` property (confirmed causes error)
- **Glob, Grep** - unknown schema validation issues with xAI

### Actually Working Tools ✅  
- **WebFetch** - has `prompt` property but works fine!

## Future Improvements

1. **Investigate Glob/Grep issues** - These tools fail even without problematic property names
2. **Property name mapping** - Could implement deep renaming of reserved properties
3. **Enable Bash tool** - Critical for many workflows, needs property transformation
4. **Full MCP support** - Would require handling 100+ complex tool schemas

## Test Scripts Created

- `test_xai_tools.py` - Tests different tool formats
- `test_property_names.py` - Identifies problematic property names  
- `test_claude_tools.py` - Tests individual Claude tools
- `test_multiple_runs.py` - Tests for non-deterministic behavior
- `capture_tools.py` - Captures full tool structure from Claude Code

## Quick Start

```bash
# Terminal 1: Start the proxy
export XAI_API_KEY="your-xai-api-key"
python grok_proxy.py

# Terminal 2: Use Claude Code
export ANTHROPIC_BASE_URL=http://localhost:8000
export ANTHROPIC_API_KEY=anything
claude --mcp-config "" --strict-mcp-config -p "Read the README.md file"
```

## Files
- `grok_proxy.py` - Original proxy using Anthropic endpoint (has property name issues)
- `grok_proxy_openai.py` - New proxy using OpenAI endpoint with conversion
- `converter.py` - Conversion functions between Anthropic and OpenAI formats
- `models.py` - Data models for both API formats
- `grok_proxy.log` / `grok_proxy_openai.log` - Request/response logs
- `requirements.txt` - Python dependencies (flask, requests)
- `Task.md` - This investigation document
- Various test scripts for debugging tool formats