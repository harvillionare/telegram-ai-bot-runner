import json
from telegram.constants import ReactionEmoji
from typing import List

from database import User

PROMPT_TEMPLATE = """
**Your name is {name}.**  

Your identity:

{bot_identity}

Below is a list of chat members and their associated information:

{members}

Response Model:

- message: The message text to send in response.
- reaction: Pick the most appropriate emoji enum to react to the last message with. Valid options: {reaction_options}.  
- reaction_strength: A float between 0 and 1 indicating how strongly you react to the last message.
"""

def generate_prompt(members: List[User], bot_name: str, bot_identity: str) -> str:
    members_json = [
        {
            "id": member.id,
            "first_name": member.first_name,
            "last_name": member.last_name,
            "username": member.username,
        }
        for member in members
    ]

    # Use format() to replace placeholders
    return PROMPT_TEMPLATE.format(
        name=bot_name,
        bot_identity=bot_identity,
        members=json.dumps(members_json, indent=4),
        reaction_options=', '.join(emoji.value for emoji in ReactionEmoji)
    )