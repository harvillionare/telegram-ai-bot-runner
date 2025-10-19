from telegram.constants import ReactionEmoji
from typing import List, Optional, Protocol

from database import Message
from pydantic import BaseModel, field_validator

class Response(BaseModel):
    message: str
    reaction: Optional[ReactionEmoji] = None
    reaction_strength: float

    @field_validator('reaction', mode='before')
    @classmethod
    def normalize_reaction(cls, value):
        if value in (None, ""):
            return None

        if isinstance(value, ReactionEmoji):
            return value

        if isinstance(value, str):
            if value in ReactionEmoji._value2member_map_:
                return ReactionEmoji(value)

            try:
                decoded = value.encode('latin-1').decode('utf-8')
            except (UnicodeDecodeError, UnicodeEncodeError):
                return None

            if decoded in ReactionEmoji._value2member_map_:
                return ReactionEmoji(decoded)

        return None

class LLMClient(Protocol):
    def generate_response(self, prompt: str, messages: List[Message]) -> Response: ...