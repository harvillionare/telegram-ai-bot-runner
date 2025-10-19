import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path

logger = logging.getLogger("telegram_ai_bot")
log_formatter = logging.Formatter('%(asctime)s - %(filename)s - %(funcName)s:%(lineno)d - %(levelname)s - %(message)s')

def configure_logger(path: Path):
    logger.setLevel(logging.DEBUG)

    # Determine console log level from env var
    console_level_str = os.getenv("LOG_CONSOLE_LEVEL", "INFO").upper()
    console_level = getattr(logging, console_level_str, logging.INFO)

    # Create console handler with an ERROR level
    console_handler = logging.StreamHandler()
    console_handler.setLevel(console_level)

    # Create file handler for all logs
    file_handler = RotatingFileHandler(path, maxBytes=5_000_000)
    file_handler.setLevel(logging.DEBUG)

    # Set log formatters
    console_handler.setFormatter(log_formatter)
    file_handler.setFormatter(log_formatter)

    # Add the handlers to the logger
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
