from datetime import datetime, timedelta, timezone
import lancedb
from pathlib import Path
import pyarrow as pa
from typing import List, Set

from embedding.client import EmbeddingClient
from logger import logger

TABLE_NAME = "embeddings"

class Rag:
    def __init__(
        self, 
        path: Path, 
        embedding_client: EmbeddingClient,  
        limit: int
    ):
        self._embedding_client = embedding_client
        self._limit = limit
        self._database = lancedb.connect(path)
        if TABLE_NAME not in self._database.table_names():
            self.table = self._database.create_table(
                TABLE_NAME, 
                schema=pa.schema([
                    pa.field("id", pa.int64()),
                    pa.field("chat_id", pa.int64()),
                    pa.field("created_at", pa.float64()),
                    pa.field("embedding", pa.list_(pa.float32(), embedding_client.dimensions)),
                ])
            )
        else:
            self.table = self._database.open_table(TABLE_NAME)

    def embed(self, message_id: int, chat_id: int, created_at: datetime, text: str) -> List[float]:
        embedding = self._embedding_client.embed(text)
        self.table.add([{
            "id": message_id, 
            "chat_id": chat_id,
            "created_at": created_at.astimezone(timezone.utc).timestamp(),
            "embedding": embedding
        }])
        return embedding

    def delete(self, message_id: int, chat_id: int) -> None:
        self.table.delete(f"id = {message_id} AND chat_id = {chat_id}")

    def search(self, chat_id: int, embedding: List[float], before: timedelta) -> Set[int]:
        query = f"chat_id = {chat_id} AND created_at < {(datetime.now(timezone.utc) - before).timestamp()}"
        messages = self.table.search(embedding).where(query).limit(self._limit).to_list()

        message_ids: Set[int] = set()
        for message in messages:
            message_ids.add(int(message["id"]))
            
        return message_ids