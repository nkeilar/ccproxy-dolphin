import os
import json
import logging
from datetime import datetime
from pathlib import Path
from flask import Flask, request, Response
import requests
from converter import convert_anthropic_to_openai, convert_openai_to_anthropic, convert_openai_stream_to_anthropic
from system_prompt_parser import parse_system_prompt, apply_custom_template, apply_prompt_config, load_prompt_config

app = Flask(__name__)

# Set up logging to file
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('unified_proxy.log'),
        logging.StreamHandler()  # Also log to console
    ]
)

# Configuration
BACKEND = os.environ.get('BACKEND', 'grok').lower()  # 'grok' or 'anthropic'
XAI_API_KEY = os.environ.get('XAI_API_KEY')
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')

# Validate configuration
if BACKEND == 'grok' and not XAI_API_KEY:
    raise ValueError("XAI_API_KEY environment variable is required for Grok backend!")
elif BACKEND == 'anthropic' and not ANTHROPIC_API_KEY:
    raise ValueError("ANTHROPIC_API_KEY environment variable is required for Anthropic backend!")

# API endpoints
XAI_BASE_URL = 'https://api.x.ai/v1'
ANTHROPIC_BASE_URL = 'https://api.anthropic.com/v1'

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

logging.info(f"Starting unified proxy with backend: {BACKEND}")

def apply_custom_system_prompt_to_request(data):
    """Apply custom system prompt to the request if enabled"""
    if not USE_CUSTOM_PROMPT or not custom_prompt_template:
        return data
    
    # Apply to system field if present
    if 'system' in data:
        try:
            config_file = PROMPT_CONFIG_FILE if os.path.exists(PROMPT_CONFIG_FILE) else None
            
            # Parse and apply custom template
            if isinstance(data['system'], str):
                sections = parse_system_prompt(data['system'])
                modified_prompt = apply_custom_template(custom_prompt_template, sections)
                if config_file:
                    config = load_prompt_config(config_file)
                    modified_prompt = apply_prompt_config(modified_prompt, config)
                data['system'] = modified_prompt
            elif isinstance(data['system'], list):
                # Handle array format
                full_text = ""
                for block in data['system']:
                    if isinstance(block, dict) and block.get("type") == "text":
                        full_text += block["text"] + "\n"
                
                sections = parse_system_prompt(full_text.strip())
                modified_prompt = apply_custom_template(custom_prompt_template, sections)
                if config_file:
                    config = load_prompt_config(config_file)
                    modified_prompt = apply_prompt_config(modified_prompt, config)
                
                # Update the first text block
                for block in data['system']:
                    if isinstance(block, dict) and block.get("type") == "text":
                        block["text"] = modified_prompt
                        break
            
            logging.info("Applied custom system prompt")
        except Exception as e:
            logging.error(f"Error applying custom prompt: {e}")
    
    return data

def save_request_response_logs(request_id, request_data, response_data, metadata):
    """Save full request/response data for analysis"""
    if not ENABLE_FULL_LOGGING:
        return
    
    # Create date-based subdirectory
    date_dir = LOG_DIR / datetime.now().strftime('%Y-%m-%d')
    date_dir.mkdir(exist_ok=True)
    
    # Save all data
    base_filename = f"{datetime.now().strftime('%H-%M-%S-%f')[:-3]}_{request_id}"
    
    # Save request
    with open(date_dir / f"{base_filename}_request.json", 'w') as f:
        json.dump(request_data, f, indent=2)
    
    # Save response
    if response_data:
        with open(date_dir / f"{base_filename}_response.json", 'w') as f:
            json.dump(response_data, f, indent=2)
    
    # Save metadata
    with open(date_dir / f"{base_filename}_metadata.json", 'w') as f:
        json.dump(metadata, f, indent=2)
    
    logging.info(f"Saved request/response logs to: {date_dir / base_filename}_*.json")

@app.route('/v1/messages', methods=['POST'])
def proxy_messages():
    start_time = datetime.now()
    request_id = f"req_{datetime.now().strftime('%Y%m%d%H%M%S%f')[:-3]}"
    
    data = request.json
    original_request = json.loads(json.dumps(data))  # Deep copy
    
    # Log request details
    logging.info("="*80)
    logging.info(f"NEW REQUEST {request_id}")
    logging.info("="*80)
    logging.info(f"Backend: {BACKEND}")
    logging.info(f"Model: {data.get('model', 'not specified')}")
    logging.info(f"Messages: {len(data.get('messages', []))}")
    
    # Apply custom system prompt if enabled
    if USE_CUSTOM_PROMPT:
        data = apply_custom_system_prompt_to_request(data)
    
    # Prepare for the appropriate backend
    if BACKEND == 'grok':
        # For Grok, we need to convert to OpenAI format
        try:
            # Map model to grok-4
            original_model = data.get('model', 'unknown')
            data['model'] = 'grok-4'
            
            # Convert to OpenAI format
            openai_request = convert_anthropic_to_openai(data)
            
            # Remove unsupported parameters
            if 'tool_choice' in openai_request:
                del openai_request['tool_choice']
            
            # Send to xAI
            headers = {
                'Authorization': f'Bearer {XAI_API_KEY}',
                'Content-Type': 'application/json'
            }
            
            stream = data.get('stream', False)
            response = requests.post(
                f'{XAI_BASE_URL}/chat/completions',
                json=openai_request,
                headers=headers,
                stream=stream
            )
            
            logging.info(f"xAI Response Status: {response.status_code}")
            
            if response.status_code != 200:
                logging.error(f"xAI Error: {response.text}")
                return Response(response.content, content_type=response.headers.get('Content-Type'), status=response.status_code)
            
            # Handle streaming
            if stream:
                def generate():
                    state = {}
                    for chunk in response.iter_lines(decode_unicode=True):
                        if chunk:
                            anthropic_events = convert_openai_stream_to_anthropic(chunk, state)
                            for event in anthropic_events:
                                yield f"{event}\n"
                            if anthropic_events:
                                yield "\n"
                    yield "\n"
                
                return Response(
                    generate(),
                    content_type='text/event-stream',
                    headers={
                        'Cache-Control': 'no-cache',
                        'X-Accel-Buffering': 'no',
                        'Connection': 'keep-alive'
                    }
                )
            
            # Non-streaming: convert response
            openai_response = response.json()
            anthropic_response = convert_openai_to_anthropic(openai_response)
            
            # Log and save
            if ENABLE_FULL_LOGGING:
                metadata = {
                    "request_id": request_id,
                    "backend": "grok",
                    "original_model": original_model,
                    "duration_ms": (datetime.now() - start_time).total_seconds() * 1000
                }
                save_request_response_logs(request_id, original_request, anthropic_response, metadata)
            
            return Response(
                json.dumps(anthropic_response),
                content_type='application/json',
                status=200
            )
            
        except Exception as e:
            logging.error(f"Error processing Grok request: {str(e)}")
            return Response(
                json.dumps({"error": f"Proxy error: {str(e)}"}),
                status=500,
                content_type='application/json'
            )
    
    else:  # BACKEND == 'anthropic'
        # For Anthropic, just forward with potential prompt modification
        try:
            headers = {
                'x-api-key': ANTHROPIC_API_KEY,
                'anthropic-version': request.headers.get('anthropic-version', '2023-06-01'),
                'Content-Type': 'application/json'
            }
            
            # Add any additional headers from the original request
            for header in ['anthropic-beta', 'anthropic-dangerous-direct-browser-access']:
                if header in request.headers:
                    headers[header] = request.headers[header]
            
            stream = data.get('stream', False)
            response = requests.post(
                f'{ANTHROPIC_BASE_URL}/messages',
                json=data,
                headers=headers,
                stream=stream
            )
            
            logging.info(f"Anthropic Response Status: {response.status_code}")
            
            if response.status_code != 200:
                logging.error(f"Anthropic Error: {response.text}")
            
            # For streaming, pass through directly
            if stream:
                def generate():
                    for chunk in response.iter_content(chunk_size=1024):
                        if chunk:
                            yield chunk
                
                return Response(
                    generate(),
                    content_type=response.headers.get('Content-Type'),
                    status=response.status_code
                )
            
            # Non-streaming
            response_data = response.json() if response.status_code == 200 else None
            
            # Log and save
            if ENABLE_FULL_LOGGING and response_data:
                metadata = {
                    "request_id": request_id,
                    "backend": "anthropic",
                    "model": data.get('model'),
                    "duration_ms": (datetime.now() - start_time).total_seconds() * 1000
                }
                save_request_response_logs(request_id, original_request, response_data, metadata)
            
            return Response(
                response.content,
                content_type=response.headers.get('Content-Type'),
                status=response.status_code
            )
            
        except Exception as e:
            logging.error(f"Error processing Anthropic request: {str(e)}")
            return Response(
                json.dumps({"error": f"Proxy error: {str(e)}"}),
                status=500,
                content_type='application/json'
            )

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=True)