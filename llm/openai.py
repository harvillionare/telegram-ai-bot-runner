import json
from openai import OpenAI
from openai.types.responses import EasyInputMessageParam, ResponseInputParam
from typing import Any, cast, Dict, List

from .client import LLMClient, Response
from database import Message

class OpenAILLMClient(LLMClient):
    def __init__(self, api_key: str, model: str, bot_id: int):
        self.model = model
        self.bot_id = bot_id
        self.openai = OpenAI(api_key=api_key)

    def generate_response(self, prompt: str, messages: List[Message]) -> Response:
        # Format messages for OpenAI request
        messages_json: list[EasyInputMessageParam] = []
        for message in messages:
            messages_json.append(EasyInputMessageParam(content=self._build_metadata_string(message), role='developer'))

            if message.user_id == self.bot_id:
                messages_json.append(EasyInputMessageParam(content=message.text, role='assistant'))
            else:
                messages_json.append(EasyInputMessageParam(content=message.text, role='user'))

        # Add prompt as the first message
        messages_json.insert(0, {"role": "developer", "content": prompt})

        # Make OpenAI request
        response = self.openai.responses.parse(
            model=self.model,
            input=cast(ResponseInputParam, messages_json),
            text_format=Response,
            timeout=30
        ).output_parsed

        if response is None:
            raise RuntimeError('Received empty output_parsed')
        
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
