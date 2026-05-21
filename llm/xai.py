from datetime import datetime, timedelta, timezone
import json
from typing import Any, Dict, List
from xai_sdk import Client
from xai_sdk.chat import assistant, system, user
from xai_sdk.tools import x_search, web_search  

from .client import LLMClient, Response
from database import Message
from logger import logger

class XAILLMClient(LLMClient):
    def __init__(self, api_key: str, model: str, bot_id: int):
        self.model = model
        self.bot_id = bot_id
        self.xai = Client(api_key=api_key)

    def generate_response(self, prompt: str, messages: List[Message]) -> Response:
        chat = self.xai.chat.create(
            model=self.model,
            tools=[
                web_search(),
                x_search(from_date=datetime.now(timezone.utc) - timedelta(hours=24)) 
            ]
        )
        chat.append(system(prompt))
        for message in messages:
            metadata_message = self._build_metadata_string(message)
            chat.append(system(metadata_message))

            logger.debug(metadata_message)
            logger.debug(message.text)

            if message.user_id == self.bot_id:
                chat.append(assistant(message.text))
            else:
                chat.append(user(message.text))

        _, parsed_response = chat.parse(Response)
        return parsed_response

    
    # Helpers
    # -----------------------------------------

    def _build_metadata_string(self, message: Message) -> str:
        metadata: Dict[str, Any] = {
            "message_id": message.id,
            "user_id": message.user_id,
            "created_at": message.created_at.isoformat() if message.created_at else None,
            "reply_to_id": message.reply_to_id,
        }
        return f"Metadata of the next message: {json.dumps(metadata)}"
