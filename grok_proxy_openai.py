import os
import json
import logging
from datetime import datetime
from pathlib import Path
from flask import Flask, request, Response
import requests
from converter import convert_anthropic_to_openai, convert_openai_to_anthropic, convert_openai_stream_to_anthropic

app = Flask(__name__)

# Set up logging to file
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('grok_proxy_openai.log'),
        logging.StreamHandler()  # Also log to console
    ]
)

# Load xAI API key from environment (set this before running)
XAI_API_KEY = os.environ.get('XAI_API_KEY')
if not XAI_API_KEY:
    raise ValueError("XAI_API_KEY environment variable is not set!")

XAI_BASE_URL = 'https://api.x.ai/v1'

# Enable full logging
ENABLE_FULL_LOGGING = os.environ.get('ENABLE_FULL_LOGGING', 'true').lower() == 'true'
LOG_DIR = Path(os.environ.get('LOG_DIR', 'logs/requests'))

# Enable custom system prompt
USE_CUSTOM_PROMPT = os.environ.get('USE_CUSTOM_PROMPT', 'false').lower() == 'true'
CUSTOM_PROMPT_FILE = os.environ.get('CUSTOM_PROMPT_FILE', 'system_prompt_template_unrestricted.txt')
PROMPT_CONFIG_FILE = os.environ.get('PROMPT_CONFIG_FILE', 'prompt_config.json')

# Load custom prompt template if enabled
custom_prompt_template = None
if USE_CUSTOM_PROMPT:
    try:
        with open(CUSTOM_PROMPT_FILE, 'r') as f:
            custom_prompt_template = f.read()
        logging.info(f"Custom system prompt enabled. Loaded template from: {CUSTOM_PROMPT_FILE}")
        
        # Check if config file exists
        if os.path.exists(PROMPT_CONFIG_FILE):
            logging.info(f"Using prompt configuration from: {PROMPT_CONFIG_FILE}")
    except Exception as e:
        logging.error(f"Failed to load custom prompt template: {e}")
        USE_CUSTOM_PROMPT = False

# Create log directory structure
if ENABLE_FULL_LOGGING:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.info(f"Full logging enabled. Logs will be saved to: {LOG_DIR}")

def save_request_response_logs(request_id, anthropic_request, openai_request, 
                               openai_response, anthropic_response, metadata, 
                               is_streaming=False, stream_content=None):
    """Save full request/response data for analysis"""
    if not ENABLE_FULL_LOGGING:
        return
    
    # Create date-based subdirectory
    date_dir = LOG_DIR / datetime.now().strftime('%Y-%m-%d')
    date_dir.mkdir(exist_ok=True)
    
    # Save all data
    base_filename = f"{datetime.now().strftime('%H-%M-%S-%f')[:-3]}_{request_id}"
    
    # Save Anthropic request
    with open(date_dir / f"{base_filename}_anthropic_request.json", 'w') as f:
        json.dump(anthropic_request, f, indent=2)
    
    # Save OpenAI request
    with open(date_dir / f"{base_filename}_openai_request.json", 'w') as f:
        json.dump(openai_request, f, indent=2)
    
    # Save OpenAI response
    if openai_response:
        with open(date_dir / f"{base_filename}_openai_response.json", 'w') as f:
            if is_streaming and stream_content:
                json.dump({"streaming": True, "content": stream_content}, f, indent=2)
            else:
                json.dump(openai_response, f, indent=2)
    
    # Save Anthropic response
    if anthropic_response:
        with open(date_dir / f"{base_filename}_anthropic_response.json", 'w') as f:
            json.dump(anthropic_response, f, indent=2)
    
    # Save metadata
    with open(date_dir / f"{base_filename}_metadata.json", 'w') as f:
        json.dump(metadata, f, indent=2)
    
    logging.info(f"Saved request/response logs to: {date_dir / base_filename}_*.json")

@app.route('/v1/messages', methods=['POST'])
def proxy_messages():
    start_time = datetime.now()
    request_id = f"req_{datetime.now().strftime('%Y%m%d%H%M%S%f')[:-3]}"
    
    data = request.json
    
    # Save a copy of the original request before any modifications
    original_anthropic_request = json.loads(json.dumps(data))
    
    # Capture request headers
    request_headers = dict(request.headers)
    
    # Log request details
    logging.info("="*80)
    logging.info(f"NEW REQUEST {request_id}")
    logging.info("="*80)
    
    # Log headers
    logging.info("Request Headers:")
    for header, value in request.headers:
        logging.info(f"  {header}: {value}")
    
    # Log original model
    original_model = data.get('model', 'not specified')
    logging.info(f"\nOriginal Model: {original_model}")
    
    # Log messages count
    messages = data.get('messages', [])
    logging.info(f"\nMessages: {len(messages)} total")
    
    # Log tools count
    tools = data.get('tools', [])
    logging.info(f"Tools: {len(tools)} total")
    if tools:
        for i, tool in enumerate(tools[:5]):  # Log first 5 tools
            logging.info(f"  Tool {i}: {tool.get('name', 'unnamed')}")
    
    # Remove unsupported params
    if 'cache_control' in data:
        logging.info("\nRemoving unsupported parameter: cache_control")
        del data['cache_control']
    
    # Clean up cache_control from nested structures
    messages = data.get('messages', [])
    for msg in messages:
        if isinstance(msg, dict):
            if 'cache_control' in msg:
                logging.info(f"Removing cache_control from message with role: {msg.get('role', 'unknown')}")
                del msg['cache_control']
            
            # Handle content if it's a list
            content = msg.get('content', [])
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and 'cache_control' in item:
                        logging.info("Removing cache_control from content item")
                        del item['cache_control']
    
    # Clean system messages
    system = data.get('system', [])
    if isinstance(system, list):
        for item in system:
            if isinstance(item, dict) and 'cache_control' in item:
                logging.info("Removing cache_control from system message")
                del item['cache_control']
    
    # Remove tool_choice if present (xAI doesn't support it in the same format)
    if 'tool_choice' in data:
        logging.info("\nRemoving tool_choice parameter")
        del data['tool_choice']
    
    # Map to grok-4 model
    data['model'] = 'grok-4'
    logging.info(f"\nMapped model: {original_model} -> grok-4")
    
    # Convert Anthropic format to OpenAI format
    logging.info("\nConverting Anthropic format to OpenAI format...")
    try:
        # Pass custom prompt template if enabled
        if USE_CUSTOM_PROMPT and custom_prompt_template:
            logging.info("Applying custom system prompt template")
            config_file = PROMPT_CONFIG_FILE if os.path.exists(PROMPT_CONFIG_FILE) else None
            openai_request = convert_anthropic_to_openai(data, custom_prompt_template, config_file)
        else:
            openai_request = convert_anthropic_to_openai(data)
        
        logging.info(f"Converted successfully. OpenAI messages: {len(openai_request['messages'])}")
        if 'tools' in openai_request:
            logging.info(f"OpenAI tools: {len(openai_request['tools'])}")
    except Exception as e:
        logging.error(f"Error converting request: {str(e)}")
        return Response(
            json.dumps({"error": f"Failed to convert request: {str(e)}"}),
            status=500,
            content_type='application/json'
        )
    
    # Prepare headers with xAI auth
    headers = {
        'Authorization': f'Bearer {XAI_API_KEY}',
        'Content-Type': 'application/json'
    }
    
    # Forward the request to xAI's OpenAI-compatible endpoint
    stream = data.get('stream', False)
    logging.info(f"\nForwarding to xAI API: {XAI_BASE_URL}/chat/completions")
    logging.info(f"Streaming: {stream}")
    
    try:
        response = requests.post(
            f'{XAI_BASE_URL}/chat/completions',
            json=openai_request,
            headers=headers,
            stream=stream
        )
        
        logging.info(f"\nResponse Status: {response.status_code}")
        
        # Handle errors
        if response.status_code != 200:
            logging.error(f"Error response: {response.text}")
            return Response(response.content, content_type=response.headers.get('Content-Type'), status=response.status_code)
        
        # Handle streaming response with conversion
        if stream:
            logging.info("Converting and returning streaming response")
            stream_chunks = []  # Collect stream chunks for logging
            
            def generate():
                state = {}  # Track streaming state
                buffer = ""  # Buffer for incomplete lines
                
                for chunk in response.iter_lines(decode_unicode=True):
                    if chunk:
                        stream_chunks.append(chunk)  # Collect for logging
                        # Convert OpenAI SSE to Anthropic SSE
                        anthropic_events = convert_openai_stream_to_anthropic(chunk, state)
                        for event in anthropic_events:
                            yield f"{event}\n"
                        if anthropic_events:  # Add blank line between events
                            yield "\n"
                
                # Log after streaming is complete
                if ENABLE_FULL_LOGGING:
                    end_time = datetime.now()
                    metadata = {
                        "request_id": request_id,
                        "start_time": start_time.isoformat(),
                        "end_time": end_time.isoformat(),
                        "duration_ms": (end_time - start_time).total_seconds() * 1000,
                        "streaming": True,
                        "original_model": original_model,
                        "headers": request_headers
                    }
                    save_request_response_logs(
                        request_id=request_id,
                        anthropic_request=original_anthropic_request,
                        openai_request=openai_request,
                        openai_response=None,
                        anthropic_response=None,
                        metadata=metadata,
                        is_streaming=True,
                        stream_content=stream_chunks
                    )
                
                # Ensure we send a final newline
                yield "\n"
            
            return Response(
                generate(),
                content_type='text/event-stream',
                headers={
                    'Cache-Control': 'no-cache',
                    'X-Accel-Buffering': 'no',  # Disable Nginx buffering
                    'Connection': 'keep-alive'
                }
            )
        
        # Non-streaming: Convert OpenAI response back to Anthropic format
        logging.info("Converting OpenAI response to Anthropic format...")
        try:
            openai_response = response.json()
            logging.info(f"OpenAI response: {json.dumps(openai_response, indent=2)}")
            anthropic_response = convert_openai_to_anthropic(openai_response)
            
            # Log usage info
            if 'usage' in anthropic_response:
                usage = anthropic_response['usage']
                logging.info(f"Usage - Input tokens: {usage['input_tokens']}, Output tokens: {usage['output_tokens']}")
            
            # Save full request/response logs
            if ENABLE_FULL_LOGGING:
                end_time = datetime.now()
                metadata = {
                    "request_id": request_id,
                    "start_time": start_time.isoformat(),
                    "end_time": end_time.isoformat(),
                    "duration_ms": (end_time - start_time).total_seconds() * 1000,
                    "streaming": False,
                    "original_model": original_model,
                    "headers": request_headers,
                    "usage": {
                        "input_tokens": anthropic_response.get('usage', {}).get('input_tokens', 0),
                        "output_tokens": anthropic_response.get('usage', {}).get('output_tokens', 0),
                        "reasoning_tokens": openai_response.get('usage', {}).get('completion_tokens_details', {}).get('reasoning_tokens', 0)
                    }
                }
                save_request_response_logs(
                    request_id=request_id,
                    anthropic_request=original_anthropic_request,
                    openai_request=openai_request,
                    openai_response=openai_response,
                    anthropic_response=anthropic_response,
                    metadata=metadata
                )
            
            return Response(
                json.dumps(anthropic_response),
                content_type='application/json',
                status=200
            )
        except Exception as e:
            logging.error(f"Error converting response: {str(e)}")
            # Return original response if conversion fails
            return Response(response.content, content_type=response.headers.get('Content-Type'), status=response.status_code)
        
    except Exception as e:
        logging.error(f"Error forwarding request: {str(e)}")
        return Response(
            json.dumps({"error": f"Failed to forward request: {str(e)}"}),
            status=500,
            content_type='application/json'
        )

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=True)  # Debug mode for testing; remove for production