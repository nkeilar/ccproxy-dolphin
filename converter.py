"""
Converter between Anthropic and OpenAI API formats
"""
import json
import time
import uuid
from typing import Any, Dict, List, Optional, Union
from system_prompt_parser import parse_system_prompt, apply_custom_template, apply_prompt_config, load_prompt_config


def apply_custom_system_prompt(system_content: Union[str, List[Dict[str, Any]]], template: str, config_file: Optional[str] = None) -> str:
    """
    Apply a custom system prompt template while preserving dynamic content.
    
    Args:
        system_content: Either a string or list of system message blocks from Anthropic
        template: Custom prompt template with placeholders
        config_file: Optional path to configuration file
        
    Returns:
        Modified system prompt as a string
    """
    # Handle array format (multiple system blocks with cache_control)
    if isinstance(system_content, list):
        # Concatenate all text blocks
        full_text = ""
        for block in system_content:
            if isinstance(block, dict) and block.get("type") == "text":
                full_text += block["text"] + "\n"
        system_text = full_text.strip()
    else:
        system_text = system_content
    
    # Parse the system prompt to extract dynamic sections
    sections = parse_system_prompt(system_text)
    
    # Apply the custom template
    modified_prompt = apply_custom_template(template, sections)
    
    # Apply configuration-based transformations if config provided
    if config_file:
        try:
            config = load_prompt_config(config_file)
            modified_prompt = apply_prompt_config(modified_prompt, config)
        except Exception as e:
            print(f"Error applying config: {e}")
            import traceback
            traceback.print_exc()
    
    return modified_prompt


def convert_anthropic_to_openai(request_data: Dict[str, Any], custom_prompt_template: Optional[str] = None, config_file: Optional[str] = None) -> Dict[str, Any]:
    """Convert Anthropic request format to OpenAI format"""
    
    # Start with basic fields
    openai_request = {
        "model": request_data["model"],
        "messages": [],
    }
    
    # Add optional fields
    if "max_tokens" in request_data:
        openai_request["max_tokens"] = request_data["max_tokens"]
    
    if "temperature" in request_data:
        openai_request["temperature"] = request_data["temperature"]
    
    # Handle system message if present
    if "system" in request_data:
        system_content = request_data["system"]
        
        # Apply custom prompt template if provided
        if custom_prompt_template:
            system_content = apply_custom_system_prompt(system_content, custom_prompt_template, config_file)
        
        openai_request["messages"].append({
            "role": "system",
            "content": system_content
        })
    
    # Convert messages
    for msg in request_data["messages"]:
        openai_msg = convert_message_to_openai(msg)
        if openai_msg:
            openai_request["messages"].append(openai_msg)
    
    # Convert tools
    if "tools" in request_data and request_data["tools"]:
        openai_request["tools"] = []
        for tool in request_data["tools"]:
            openai_tool = {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool["input_schema"]
                }
            }
            openai_request["tools"].append(openai_tool)
    
    # Handle tool_choice
    if "tool_choice" in request_data:
        openai_request["tool_choice"] = request_data["tool_choice"]
    
    return openai_request


def convert_message_to_openai(msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Convert a single Anthropic message to OpenAI format"""
    
    role = msg["role"]
    content = msg["content"]
    
    # Handle tool results (Anthropic) -> tool messages (OpenAI)
    if role == "tool":
        return {
            "role": "tool",
            "content": json.dumps(content) if not isinstance(content, str) else content,
            "tool_call_id": msg.get("tool_use_id", "")
        }
    
    # Handle string content
    if isinstance(content, str):
        return {
            "role": role,
            "content": content
        }
    
    # Handle content blocks
    if isinstance(content, list):
        text_parts = []
        tool_calls = []
        tool_results = []
        
        for block in content:
            if block["type"] == "text":
                text_parts.append(block["text"])
            elif block["type"] == "tool_use":
                tool_call = {
                    "id": block["id"],
                    "type": "function",
                    "function": {
                        "name": block["name"],
                        "arguments": json.dumps(block["input"])
                    }
                }
                tool_calls.append(tool_call)
            elif block["type"] == "tool_result":
                # Handle tool results within user messages
                tool_result = {
                    "role": "tool",
                    "content": block["content"],
                    "tool_call_id": block.get("tool_use_id", "")
                }
                # If it's an error, prepend [ERROR] to help the model understand
                if block.get("is_error", False):
                    tool_result["content"] = f"[ERROR] {block['content']}"
                tool_results.append(tool_result)
        
        # If we have tool results, return them as separate messages
        if tool_results:
            # Return the first tool result (typically there's only one per message)
            # Multiple tool results would need to be handled by the caller
            return tool_results[0]
        
        openai_msg = {"role": role}
        
        if text_parts:
            openai_msg["content"] = "\n".join(text_parts)
        else:
            openai_msg["content"] = ""
            
        if tool_calls:
            openai_msg["tool_calls"] = tool_calls
            
        return openai_msg
    
    return None


def convert_openai_to_anthropic(response_data: Dict[str, Any], request_id: Optional[str] = None) -> Dict[str, Any]:
    """Convert OpenAI response format to Anthropic format"""
    
    if not request_id:
        request_id = f"msg_{uuid.uuid4().hex[:12]}"
    
    # Extract the first choice (Anthropic doesn't support multiple choices)
    choice = response_data["choices"][0]
    message = choice["message"]
    
    # Build content blocks
    content_blocks = []
    
    # Add text content if present
    if message.get("content"):
        content_blocks.append({
            "type": "text",
            "text": message["content"]
        })
    
    # Add tool calls if present
    if "tool_calls" in message and message["tool_calls"]:
        for tool_call in message["tool_calls"]:
            content_blocks.append({
                "type": "tool_use",
                "id": tool_call["id"],
                "name": tool_call["function"]["name"],
                "input": json.loads(tool_call["function"]["arguments"])
            })
    
    # Map finish reason
    finish_reason = choice["finish_reason"]
    if finish_reason == "stop":
        stop_reason = "end_turn"
    elif finish_reason == "length":
        stop_reason = "max_tokens"
    elif finish_reason == "tool_calls":
        stop_reason = "tool_use"
    else:
        stop_reason = finish_reason
    
    # Build Anthropic response
    anthropic_response = {
        "id": request_id,
        "type": "message",
        "role": "assistant",
        "content": content_blocks,
        "model": response_data["model"],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {
            "input_tokens": response_data["usage"]["prompt_tokens"],
            "output_tokens": response_data["usage"]["completion_tokens"]
        }
    }
    
    return anthropic_response


def convert_openai_stream_to_anthropic(chunk_line: str, state: Dict[str, Any]) -> List[str]:
    """
    Convert a single OpenAI streaming chunk to Anthropic SSE format.
    
    Args:
        chunk_line: A line from OpenAI SSE stream (e.g., "data: {...}")
        state: Mutable state dict to track message progress
        
    Returns:
        List of Anthropic SSE formatted lines to send
    """
    events = []
    
    # Skip empty lines
    if not chunk_line.strip():
        return events
        
    # Handle the [DONE] message
    if chunk_line.strip() == "data: [DONE]":
        # Send message_stop event
        events.append("event: message_stop")
        events.append(f"data: {json.dumps({'type': 'message_stop'})}")
        return events
    
    # Parse the JSON data
    if not chunk_line.startswith("data: "):
        return events
        
    try:
        chunk_data = json.loads(chunk_line[6:])  # Skip "data: " prefix
    except json.JSONDecodeError:
        return events
    
    # Initialize state if needed
    if not state.get('started'):
        state['started'] = True
        state['message_id'] = f"msg_{uuid.uuid4().hex[:12]}"
        state['content_blocks'] = []
        state['current_tool_calls'] = {}
        state['input_tokens'] = 0
        state['output_tokens'] = 0
        
        # Send message_start event
        message_start = {
            "type": "message_start",
            "message": {
                "id": state['message_id'],
                "type": "message",
                "role": "assistant",
                "content": [],
                "model": chunk_data.get("model", "grok-4"),
                "usage": {
                    "input_tokens": 0,
                    "output_tokens": 0
                }
            }
        }
        events.append("event: message_start")
        events.append(f"data: {json.dumps(message_start)}")
    
    # Process choices
    if "choices" in chunk_data and chunk_data["choices"]:
        choice = chunk_data["choices"][0]
        delta = choice.get("delta", {})
        
        # Handle content
        if "content" in delta and delta["content"]:
            # Initialize content block if needed
            if not state.get('content_block_started'):
                state['content_block_started'] = True
                content_block_start = {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {
                        "type": "text",
                        "text": ""
                    }
                }
                events.append("event: content_block_start")
                events.append(f"data: {json.dumps(content_block_start)}")
            
            # Send content delta
            content_delta = {
                "type": "content_block_delta",
                "index": 0,
                "delta": {
                    "type": "text_delta",
                    "text": delta["content"]
                }
            }
            events.append("event: content_block_delta")
            events.append(f"data: {json.dumps(content_delta)}")
        
        # Handle tool calls
        if "tool_calls" in delta:
            for tool_call in delta["tool_calls"]:
                tool_index = tool_call["index"]
                
                # Initialize tool call if new
                if tool_index not in state['current_tool_calls']:
                    state['current_tool_calls'][tool_index] = {
                        "id": tool_call.get("id", ""),
                        "name": "",
                        "arguments": ""
                    }
                    
                    # Send content_block_start for tool
                    tool_block_start = {
                        "type": "content_block_start",
                        "index": tool_index + 1,  # +1 because text content is index 0
                        "content_block": {
                            "type": "tool_use",
                            "id": tool_call.get("id", ""),
                            "name": "",
                            "input": {}
                        }
                    }
                    events.append("event: content_block_start")
                    events.append(f"data: {json.dumps(tool_block_start)}")
                
                # Update tool call data
                if "function" in tool_call:
                    if "name" in tool_call["function"]:
                        state['current_tool_calls'][tool_index]["name"] = tool_call["function"]["name"]
                    if "arguments" in tool_call["function"]:
                        state['current_tool_calls'][tool_index]["arguments"] += tool_call["function"]["arguments"]
                        
                        # Try to parse arguments as we receive them
                        try:
                            args_json = json.loads(state['current_tool_calls'][tool_index]["arguments"])
                            tool_delta = {
                                "type": "content_block_delta",
                                "index": tool_index + 1,
                                "delta": {
                                    "type": "input_json_delta",
                                    "partial_json": json.dumps(args_json)
                                }
                            }
                            events.append("event: content_block_delta")
                            events.append(f"data: {json.dumps(tool_delta)}")
                        except json.JSONDecodeError:
                            # Arguments not complete yet, send partial
                            tool_delta = {
                                "type": "content_block_delta",
                                "index": tool_index + 1,
                                "delta": {
                                    "type": "input_json_delta",
                                    "partial_json": tool_call["function"]["arguments"]
                                }
                            }
                            events.append("event: content_block_delta")
                            events.append(f"data: {json.dumps(tool_delta)}")
        
        # Handle finish reason
        if "finish_reason" in choice and choice["finish_reason"]:
            # Send content_block_stop for any open blocks
            if state.get('content_block_started'):
                content_block_stop = {
                    "type": "content_block_stop",
                    "index": 0
                }
                events.append("event: content_block_stop")
                events.append(f"data: {json.dumps(content_block_stop)}")
            
            # Send content_block_stop for each tool
            for tool_index in state['current_tool_calls']:
                tool_block_stop = {
                    "type": "content_block_stop",
                    "index": tool_index + 1
                }
                events.append("event: content_block_stop")
                events.append(f"data: {json.dumps(tool_block_stop)}")
            
            # Send message_delta with stop_reason
            message_delta = {
                "type": "message_delta",
                "delta": {
                    "stop_reason": map_openai_finish_reason(choice["finish_reason"]),
                    "stop_sequence": None
                },
                "usage": {
                    "output_tokens": state.get('output_tokens', 0)
                }
            }
            events.append("event: message_delta")
            events.append(f"data: {json.dumps(message_delta)}")
    
    # Track usage if provided
    if "usage" in chunk_data:
        state['input_tokens'] = chunk_data["usage"].get("prompt_tokens", 0)
        state['output_tokens'] = chunk_data["usage"].get("completion_tokens", 0)
    
    return events


def map_openai_finish_reason(openai_reason: str) -> str:
    """Map OpenAI finish reasons to Anthropic stop reasons."""
    mapping = {
        "stop": "end_turn",
        "length": "max_tokens",
        "tool_calls": "tool_use",
        "function_call": "tool_use",
        "content_filter": "stop_sequence"
    }
    return mapping.get(openai_reason, "end_turn")