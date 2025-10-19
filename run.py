import argparse
from datetime import timedelta
from functools import partial
import json
from pathlib import Path
from pytimeparse.timeparse import timeparse
from telegram.ext import Application, ApplicationBuilder

from bot import TelegramBot
from database import Database
from embedding.client import EmbeddingClient
from embedding.openai import OpenAIEmbeddingClient
from llm.client import LLMClient
from llm.openai import OpenAILLMClient
from llm.xai import XAILLMClient
from logger import configure_logger, logger
from rag import Rag
from vision.client import VisionClient
from vision.openai import OpenAIVisionClient

def start(folder_name: str):
    bot_path = Path("bots") / folder_name
    config_path = bot_path / "config.json"
    identity_path = bot_path/ "identity.txt"

    resources_path = bot_path / "resources"
    resources_path.mkdir(parents=True, exist_ok=True)

    configure_logger(path=resources_path / "app.log")

    if not config_path.exists():
        raise FileNotFoundError(f"config file not found: {config_path}")

    with open(config_path, "r") as config_file:
        config_json = json.load(config_file)

    if not identity_path.exists():
        raise FileNotFoundError(f"identity file not found: {identity_path}")
    
    with open(identity_path, "r") as identity_file:
        identity = identity_file.read()

    telegram_token = config_json.get("telegram_token")
    if not telegram_token:
        raise ValueError("config must contain telegram_token")
    
    telegram = ApplicationBuilder().token(telegram_token).build()
    telegram.post_init = partial(telegram_post_init, config_json, identity, resources_path)
    telegram.run_polling()
    
def _parse_llm(llm_config_json, bot_id: int) -> LLMClient:
    if "openai" in llm_config_json:
        openai_llm_config_json = llm_config_json["openai"]

        api_key = openai_llm_config_json.get("api_key")
        if not api_key:
            raise ValueError("openai llm config must contain api_key")
        
        model = openai_llm_config_json.get("model")
        if not model:
            raise ValueError("openai llm config must contain model")
        
        return OpenAILLMClient(api_key=api_key, model=model, bot_id=bot_id)
    elif "xai" in llm_config_json:
        xai_llm_config_json = llm_config_json["xai"]

        api_key = xai_llm_config_json.get("api_key")
        if not api_key:
            raise ValueError("xai llm config must contain api_key")
        
        model = xai_llm_config_json.get("model")
        if not model:
            raise ValueError("xai llm config must contain model")
        
        return XAILLMClient(api_key=api_key, model=model, bot_id=bot_id)
    else:
        raise ValueError(f"llm config contained unsupported provider: {llm_config_json}")
    
def _parse_vision(vision_config_json) -> VisionClient:
    if "openai" in vision_config_json:
        openai_vision_config_json = vision_config_json["openai"]

        api_key = openai_vision_config_json.get("api_key")
        if not api_key:
            raise ValueError("openai vision config must contain api_key")
        
        model = openai_vision_config_json.get("model")
        if not model:
            raise ValueError("openai vision config must contain model")
        
        return OpenAIVisionClient(api_key=api_key, model=model)
    else:
        raise ValueError(f"vision config contained unsupported provider: {vision_config_json}")

def _parse_rag(rag_config_json, path: Path) -> Rag:    
    limit = rag_config_json.get("limit")
    if not limit:
        raise ValueError("rag config must contain limit")
    
    embedding_config_json = rag_config_json.get("embedding")
    if not embedding_config_json:
        raise ValueError("rag config must contain embedding")
    
    embedding_client = _parse_embedding(embedding_config_json=embedding_config_json)

    return Rag(path=path, embedding_client=embedding_client, limit=limit)
    
def _parse_embedding(embedding_config_json) -> EmbeddingClient:
    if "openai" in embedding_config_json:
        openai_embedding_config_json = embedding_config_json["openai"]

        api_key = openai_embedding_config_json.get("api_key")
        if not api_key:
            raise ValueError("openai embedding config must contain api_key")
        
        model = openai_embedding_config_json.get("model")
        if not model:
            raise ValueError("openai embedding config must contain model")
        
        dimensions = openai_embedding_config_json.get("dimensions")
        if not dimensions:
            raise ValueError("openai embedding config must contain model")
        
        return OpenAIEmbeddingClient(api_key=api_key, model=model, dimensions=dimensions)
    else:
        raise ValueError(f"embedding config contained unsupported provider: {embedding_config_json}")

async def telegram_post_init(config_json, identity: str, path: Path, self: Application):
    admin_user_id = config_json.get("admin_user_id")
    if not admin_user_id:
        raise ValueError("config must contain admin_user_id")
    
    context_window_string = config_json.get("context_window")
    if not context_window_string:
        raise ValueError("config must contain context_window")
    
    context_window_seconds = timeparse(context_window_string)
    if context_window_seconds is None:
        raise ValueError(f"config context_window is malformed: {context_window_string}")
    context_window = timedelta(seconds=context_window_seconds)
    
    reaction_threshold = config_json.get("reaction_threshold")
    if not reaction_threshold:
        raise ValueError("config must contain reaction_threshold")
    
    llm_config_json = config_json.get("llm")
    if not llm_config_json:
        raise ValueError("config must contain llm")
    
    llm = _parse_llm(llm_config_json=llm_config_json, bot_id=self.bot.id)

    vision_config_json = config_json.get("vision")
    if not vision_config_json:
        raise ValueError("config must contain vision")
    
    vision = _parse_vision(vision_config_json=vision_config_json)

    rag_config_json = config_json.get("rag")
    if not rag_config_json:
        raise ValueError("config must contain rag")
    
    rag = _parse_rag(rag_config_json=rag_config_json, path=path)

    bot_id = self.bot.id
    bot_name = self.bot.first_name
    bot_username = self.bot.username

    database = Database(
        path=path,
        admin_user_id=admin_user_id,
        bot_id=bot_id, 
        bot_name=bot_name, 
        bot_username=bot_username
    )

    telegram_bot = TelegramBot(
        id=bot_id,
        name=bot_name,
        username=bot_username,
        admin_user_id=admin_user_id, 
        context_window=context_window,
        reaction_threshold=reaction_threshold,
        identity=identity,
        path=path,
        telegram=self, 
        database=database,
        llm=llm, 
        vision=vision,
        rag=rag
    )
    await telegram_bot.start()
    logger.info(f"Bot started: {bot_id}")

if __name__ == "__main__":
    arg_parser = argparse.ArgumentParser(description="Run Telegram bot whose configuration lives in specified folder.")
    arg_parser.add_argument("folder_name", type=str, help="Folder name of the Telegram bot")
    args = arg_parser.parse_args()
    start(folder_name=args.folder_name)
