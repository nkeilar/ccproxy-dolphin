import os
import json
import logging
from datetime import datetime
from flask import Flask, request, Response
import requests

app = Flask(__name__)

# Set up logging to file
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('grok_proxy.log'),
        logging.StreamHandler()  # Also log to console
    ]
)

# Load xAI API key from environment (set this before running)
XAI_API_KEY = os.environ.get('XAI_API_KEY')
if not XAI_API_KEY:
    raise ValueError("XAI_API_KEY environment variable is not set!")

XAI_BASE_URL = 'https://api.x.ai/v1'

@app.route('/v1/messages', methods=['POST'])
def proxy_messages():
    data = request.json
    
    # Log request details
    logging.info("="*80)
    logging.info("NEW REQUEST")
    logging.info("="*80)
    
    # Log headers
    logging.info("Request Headers:")
    for header, value in request.headers:
        logging.info(f"  {header}: {value}")
    
    # Log original model
    original_model = data.get('model', 'not specified')
    logging.info(f"\nOriginal Model: {original_model}")
    
    # Log messages/prompt
    messages = data.get('messages', [])
    logging.info(f"\nMessages ({len(messages)} total):")
    for i, msg in enumerate(messages):
        role = msg.get('role', 'unknown')
        content = msg.get('content', '')
        # Truncate very long content for logging
        if len(content) > 500:
            content = content[:500] + "... [truncated]"
        logging.info(f"  [{i}] {role}: {content}")
    
    # Log other parameters
    logging.info(f"\nOther parameters:")
    for key, value in data.items():
        if key not in ['model', 'messages']:
            logging.info(f"  {key}: {value}")

    # Remove unsupported params (add more if you encounter others)
    if 'cache_control' in data:
        logging.info("\nRemoving unsupported parameter: cache_control")
        del data['cache_control']
    
    # Also remove cache_control from messages if present
    messages = data.get('messages', [])
    for msg in messages:
        if isinstance(msg, dict) and 'cache_control' in msg:
            logging.info(f"\nRemoving cache_control from message with role: {msg.get('role', 'unknown')}")
            del msg['cache_control']
        
        # Handle tool result messages - convert to format xAI understands
        if msg.get('role') == 'tool':
            logging.info(f"\n🔧 Converting tool result message with id: {msg.get('tool_use_id', 'unknown')}")
            # Keep the tool message as-is - xAI supports Anthropic format
            
        # Handle content if it's a list of objects
        content = msg.get('content', [])
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and 'cache_control' in item:
                    logging.info(f"\nRemoving cache_control from content item")
                    del item['cache_control']
    
    # Also check system messages
    system = data.get('system', [])
    if isinstance(system, list):
        for item in system:
            if isinstance(item, dict) and 'cache_control' in item:
                logging.info(f"\nRemoving cache_control from system message")
                del item['cache_control']
    
    # xAI expects Anthropic format! Filter out problematic tools
    if 'tools' in data:
        original_tools = data['tools']
        safe_tools = []
        
        for tool in original_tools:
            if isinstance(tool, dict) and 'input_schema' in tool:
                schema = tool['input_schema']
                
                # Remove fields that might cause issues
                if '$schema' in schema:
                    del schema['$schema']
                if 'additionalProperties' in schema:
                    del schema['additionalProperties']
                
                # Check for problematic property names or known problematic tools
                skip_tool = False
                tool_name = tool.get('name', '')
                
                # Skip known problematic tools
                if tool_name in ['Glob', 'Grep']:
                    logging.info(f"⚠️  Skipping tool '{tool_name}' - known compatibility issues with xAI")
                    skip_tool = True
                elif 'properties' in schema:
                    props = schema['properties']
                    # Only skip tools with 'description' as property name (verified to cause errors)
                    if 'description' in props:
                        logging.info(f"⚠️  Skipping tool '{tool_name}' - has 'description' property which causes xAI errors")
                        skip_tool = True
                
                if not skip_tool:
                    safe_tools.append(tool)
            else:
                # Keep tools without input_schema
                safe_tools.append(tool)
        
        data['tools'] = safe_tools
        logging.info(f"\n✅ Filtered from {len(original_tools)} to {len(safe_tools)} safe tools")
        
        # Log accepted tools for debugging
        for i, tool in enumerate(safe_tools[:5]):
            logging.info(f"  Accepted Tool {i}: {tool.get('name', 'unnamed')}")
    
    # Remove tool_choice - it's causing format issues with xAI
    if 'tool_choice' in data:
        logging.info("\nRemoving tool_choice parameter")
        del data['tool_choice']

    # Always map to grok-4 regardless of input model
    data['model'] = 'grok-4'
    logging.info(f"\nMapped model: {original_model} -> grok-4")

    # Prepare headers with xAI auth
    headers = {
        'Authorization': f'Bearer {XAI_API_KEY}',
        'Content-Type': 'application/json'
    }

    # Forward the request to xAI (supports streaming)
    stream = data.get('stream', False)
    logging.info(f"\nForwarding to xAI API: {XAI_BASE_URL}/messages")
    logging.info(f"Streaming: {stream}")
    
    try:
        response = requests.post(
            f'{XAI_BASE_URL}/messages',
            json=data,
            headers=headers,
            stream=stream
        )
        
        logging.info(f"\nResponse Status: {response.status_code}")
        
        # Handle streaming response
        if stream:
            logging.info("Returning streaming response")
            def generate():
                for chunk in response.iter_content(chunk_size=1024):
                    if chunk:
                        yield chunk
            return Response(generate(), content_type=response.headers.get('Content-Type'), status=response.status_code)

        # Non-streaming: Return JSON
        logging.info("Returning non-streaming response")
        # Log response content (truncated if too long)
        try:
            response_text = response.text
            if len(response_text) > 1000:
                response_text = response_text[:1000] + "... [truncated]"
            logging.info(f"Response content: {response_text}")
        except:
            logging.info("Could not log response content")
            
        return Response(response.content, content_type=response.headers.get('Content-Type'), status=response.status_code)
        
    except Exception as e:
        logging.error(f"Error forwarding request: {str(e)}")
        raise

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=True)  # Debug mode for testing; remove for production

