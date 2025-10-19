import json
from typing import Any, cast, Dict, List
from xai_sdk import Client
from xai_sdk.chat import assistant, system, user

from .client import LLMClient, Response
from database import Message

class XAILLMClient(LLMClient):
    def __init__(self, api_key: str, model: str, bot_id: int):
        self.model = model
        self.bot_id = bot_id
        self.xai = Client(api_key=api_key)

    def generate_response(self, prompt: str, messages: List[Message]) -> Response:
        chat = self.xai.chat.create(model=self.model)
        chat.append(system(prompt))
        for message in messages:
            chat.append(system(self._build_metadata_string(message)))
            if message.user_id == self.bot_id:
                chat.append(assistant(message.text))
            else:
                chat.append(user(message.text))

        # Make xAI request
        xai_response, response = chat.parse(Response)
        assert isinstance(response, Response)
        
        return response
    
    # Helpers
    # -----------------------------------------

    def _build_metadata_string(self, message: Message) -> str:
        metadata: Dict[str, Any] = {
            "id": message.id,
            "sender_id": message.user_id,
            "created_at": message.created_at.isoformat() if message.created_at else None,
            "reply_to_id": message.reply_to_id,
        }
        return f"Metadata of the next message: {json.dumps(metadata)}"
