import os
import re

def sanitize_markdown(text: str) -> str:
    """Sanitize Markdown for Telegram messages.

    Telegram's Markdown parser supports only a limited subset of syntax.
    This function converts certain Markdown syntax to what Telegram supports.

      • Converts double asterisk bold (`**bold**`) to single-asterisk bold (`*bold*`).
      • Converts Markdown headers (`# Heading`) into bold text.

    Args:
        text: The Markdown string to normalize.

    Returns:
        str: A sanitized Markdown string safe for Telegram.
    """

    # Convert double asterisk bold to single asterisk bold.  
    text = text.replace('**', '*')
    
    # Replace all headers in the text with bold.
    pattern = re.compile(r'^(#+)\s*(.*)', re.MULTILINE)    
    def replace_header_with_bold(match):
        return f"*{match.group(2)}*"
    text = re.sub(pattern, replace_header_with_bold, text)

    return text