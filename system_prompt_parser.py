import re
import json
from typing import Dict, Optional, Tuple, Any

def parse_system_prompt(system_text: str) -> Dict[str, str]:
    """
    Parse the system prompt to extract dynamic sections.
    Returns a dictionary with extracted sections.
    """
    sections = {}
    
    # Extract environment info
    env_match = re.search(r'<env>(.*?)</env>', system_text, re.DOTALL)
    if env_match:
        sections['env_info'] = env_match.group(0)  # Include tags
    
    # Extract model info (everything from "You are powered by" to the next section)
    model_match = re.search(
        r'(You are powered by the model named.*?Assistant knowledge cutoff is [^\n]+)',
        system_text, re.DOTALL
    )
    if model_match:
        sections['model_info'] = model_match.group(1)
    
    # Extract MCP Server Instructions if present
    mcp_match = re.search(
        r'(# MCP Server Instructions.*?)(?=\n#|\nIMPORTANT:|\Z)',
        system_text, re.DOTALL
    )
    if mcp_match:
        sections['mcp_instructions'] = mcp_match.group(1)
    
    # Extract the main content (everything else)
    # Remove the extracted sections to get the main content
    main_content = system_text
    for key, value in sections.items():
        if value and key != 'main_content':
            main_content = main_content.replace(value, '')
    
    # Clean up extra newlines
    main_content = re.sub(r'\n{3,}', '\n\n', main_content).strip()
    sections['main_content'] = main_content
    
    return sections


def apply_custom_template(template: str, sections: Dict[str, str]) -> str:
    """
    Apply extracted sections to a custom template.
    Template should contain placeholders like {{ENV_INFO}}, {{MODEL_INFO}}, etc.
    """
    result = template
    
    # Define placeholder mappings
    placeholders = {
        '{{ENV_INFO}}': sections.get('env_info', ''),
        '{{MODEL_INFO}}': sections.get('model_info', ''),
        '{{MCP_INSTRUCTIONS}}': sections.get('mcp_instructions', ''),
    }
    
    # Replace placeholders
    for placeholder, value in placeholders.items():
        result = result.replace(placeholder, value)
    
    # Clean up extra newlines
    result = re.sub(r'\n{3,}', '\n\n', result)
    
    return result.strip()


def split_intro_and_content(system_text: str) -> Tuple[str, str]:
    """
    Split the system prompt into intro line and main content.
    Used when system prompt is provided as an array with cache_control.
    """
    # The first line is typically "You are Claude Code, Anthropic's official CLI for Claude."
    lines = system_text.split('\n', 1)
    if len(lines) > 1:
        return lines[0].strip(), lines[1].strip()
    return system_text.strip(), ""


def apply_prompt_config(prompt: str, config: Dict[str, Any]) -> str:
    """
    Apply configuration-based transformations to the prompt.
    """
    result = prompt
    
    # Remove Claude/Anthropic references if configured
    if config.get('remove_claude_references', False):
        result = re.sub(r'Claude Code', config.get('system_name', 'AI Assistant'), result)
        result = re.sub(r'claude\.ai/code', '', result)
        result = re.sub(r'You are Claude Code[^.]*\.', f"You are {config.get('system_name', 'an AI assistant')}.", result)
    
    if config.get('remove_anthropic_references', False):
        result = re.sub(r'Anthropic\'s official CLI for Claude', 'an advanced AI coding assistant', result)
        feedback_url = config.get('custom_help_info', {}).get('feedback_url', '')
        if feedback_url:
            result = re.sub(r'https://github\.com/anthropics/claude-code/issues', feedback_url, result)
        else:
            result = re.sub(r'https://github\.com/anthropics/claude-code/issues', '', result)
        
        doc_url = config.get('custom_help_info', {}).get('documentation_url', '')
        if doc_url:
            result = re.sub(r'https://docs\.anthropic\.com/en/docs/claude-code[^\\s]*', doc_url, result)
        else:
            result = re.sub(r'https://docs\.anthropic\.com/en/docs/claude-code[^\\s]*', '', result)
        # Remove the entire Claude Code documentation section
        result = re.sub(
            r'When the user directly asks about Claude Code.*?Example: https://docs\.anthropic\.com/en/docs/claude-code/cli-usage\n',
            '',
            result,
            flags=re.DOTALL
        )
    
    # Remove defensive restrictions if configured
    if config.get('remove_defensive_restrictions', False):
        # Remove security restrictions
        result = re.sub(
            r'IMPORTANT: Assist with defensive security tasks only\.[^.]+\.',
            '',
            result
        )
        # Remove URL generation restrictions
        result = re.sub(
            r'IMPORTANT: You must NEVER generate or guess URLs[^.]+\.',
            '',
            result
        )
    
    # Update model references
    if config.get('model_name_override'):
        result = re.sub(r'Opus 4', config['model_name_override'], result)
        result = re.sub(r'claude-opus-4-\d+', config['model_name_override'].lower().replace(' ', '-'), result)
    
    # Apply custom placeholders
    placeholders = config.get('placeholders', {})
    for placeholder, value in placeholders.items():
        result = result.replace(placeholder, value)
    
    # Update help/feedback section
    if config.get('custom_help_info'):
        help_info = config['custom_help_info']
        if help_info.get('help_command') or help_info.get('feedback_url'):
            new_help_section = "If the user asks for help or wants to give feedback inform them of the following:\n"
            if help_info.get('help_command'):
                new_help_section += f"- {help_info['help_command']}: Get help\n"
            if help_info.get('feedback_url'):
                new_help_section += f"- To give feedback: {help_info['feedback_url']}\n"
            
            # Replace the existing help section
            result = re.sub(
                r'If the user asks for help[^:]+:\s*\n(?:- [^\n]+\n)*',
                new_help_section,
                result
            )
    
    # Clean up extra newlines
    result = re.sub(r'\n{3,}', '\n\n', result)
    
    return result.strip()


def load_prompt_config(config_file: str) -> Dict[str, Any]:
    """Load prompt configuration from JSON file."""
    try:
        with open(config_file, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading config: {e}")
        return {}