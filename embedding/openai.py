from openai import OpenAI
from typing import List

from .client import EmbeddingClient

class OpenAIEmbeddingClient(EmbeddingClient):
    def __init__(self, api_key: str, model: str, dimensions: int):
        self._client = OpenAI(api_key=api_key)
        self._model = model
        self._dimensions = dimensions

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def embed(self, text: str) -> List[float]:
        embeddings = self._client.embeddings.create(model=self._model, input=text, dimensions=self._dimensions)
        return embeddings.data[0].embedding