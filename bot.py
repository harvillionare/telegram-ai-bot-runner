import asyncio
import base64
from datetime import timedelta
from functools import partial
import logging
from pathlib import Path
from telegram import (
    File, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup, 
    Message as TelegramMessage, 
    Update, 
    User as TelegramUser
)
from telegram.constants import ChatAction
from telegram.ext import (
    Application, 
    CallbackContext, 
    CallbackQueryHandler, 
    CommandHandler,
    ContextTypes,
    ExtBot, 
    filters, 
    MessageHandler
)

from database import Database, Message, User
from helpers import sanitize_markdown
from logger import log_formatter, logger
from llm.client import LLMClient
from prompt import generate_prompt
from rag import Rag
from vision.client import VisionClient

ACCESS_APPROVE_PREFIX = 'approve'
ACCESS_DENY_PREFIX = 'deny'
ACCESS_DELIMITER = '_'

# Class to handle error logs and send an alert
class AdminAlertHandler(logging.Handler):
    def __init__(self, admin_user_id: int, bot: ExtBot):
        super().__init__()
        self.admin_user_id = admin_user_id
        self.bot = bot

    def emit(self, record):
        log_entry = self.format(record)
        asyncio.create_task(self.bot.send_message(text=log_entry, chat_id=self.admin_user_id))

class TelegramBot:

    def __init__(
        self,
        id: int,
        name: str, 
        username: str,
        admin_user_id: int,
        context_window: timedelta,
        reaction_threshold: float,
        identity: str,
        path: Path,
        telegram: Application,
        database: Database,
        llm: LLMClient, 
        vision: VisionClient, 
        rag: Rag
    ):
        self.id = id
        self.name = name
        self.username = username
        self.admin_user_id = admin_user_id
        self.context_window = context_window
        self.reaction_threshold = reaction_threshold
        self.identity = identity
        self.telegram = telegram
        self.database = database
        self.llm = llm
        self.vision = vision
        self.rag = rag
        
        self.images_path = path / "images"
        self.images_path.mkdir(exist_ok=True)

        # Set up custom alerts for error logs
        admin_handler = AdminAlertHandler(bot=self.telegram.bot, admin_user_id=admin_user_id)
        admin_handler.setLevel(logging.ERROR)
        admin_handler.setFormatter(log_formatter)

    async def start(self):
        self.telegram.add_handler(MessageHandler(filters.UpdateType.EDITED_MESSAGE, partial(self.on_edit_text)))
        self.telegram.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, partial(self.on_text)))
        self.telegram.add_handler(MessageHandler(filters.PHOTO, partial(self.on_photo)))
        self.telegram.add_handler(CommandHandler('start', partial(self.on_start)))
        self.telegram.add_handler(CallbackQueryHandler(self.on_callback))
        
        commands = []
        await self.telegram.bot.set_my_commands(commands=commands)

    # -----------------------------------------
    # Commands
    # -----------------------------------------

    async def on_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message is None or update.message.from_user is None:
            return

        user = await self._ensure_access(telegram_user=update.message.from_user)
        if user is None:
            return
    
        await update.message.reply_text('Welcome!') 

    # -----------------------------------------
    # Text
    # -----------------------------------------

    async def on_text(self, update: Update, context: CallbackContext):
        if update.message is None or update.message.from_user is None or update.message.text is None:
            return
        
        message, from_user, text = update.message, update.message.from_user, update.message.text

        # Ensure user access has been approved
        user = await self._ensure_access(telegram_user=from_user)
        if user is None:
            return   

        logger.info(f'msg_in - chat_id: {message.chat_id} - msg_id: {message.id} - user_id: {from_user.id}')
        logger.debug(f'msg_text: {message.text}')

        with self.database.Session.begin() as session:
            # Store message
            new_message = Message(
                id=message.id,
                user_id=from_user.id, 
                chat_id=message.chat_id, 
                text=text,
                created_at=message.date,
                reply_to_id=message.reply_to_message.id if message.reply_to_message else None
            )

            session.add(new_message)
            logger.info(f'msg_in_persisted - chat_id: {message.chat_id} - msg_id: {message.id}')

        try:
            # Generate and store the message's embedding
            embedding = self.rag.embed(
                message_id=message.id, 
                chat_id=message.chat_id, 
                text=text, 
                created_at=message.date
            )

            bot_mentioned = self.name.lower() in text.lower()
            is_private_chat = message.chat.type == "private"
            is_reply_to_bot = (
                message.reply_to_message
                and message.reply_to_message.from_user
                and message.reply_to_message.from_user.id == self.id
            )

            # Conditions to ask LLM for a reply
            if bot_mentioned or is_private_chat or is_reply_to_bot:
                await context.bot.send_chat_action(message.chat_id, action=ChatAction.TYPING)
                logger.info(f'llm_request - chat_id: {message.chat_id} - msg_id: {message.id}')

                # Get RAG messages for LLM context
                rag_message_ids = self.rag.search(
                    chat_id=message.chat_id, 
                    embedding=embedding, 
                    before=self.context_window
                )
                context_messages = self.database.get_messages(chat_id=message.chat_id, message_ids=rag_message_ids)

                # Get recent messages for LLM context
                context_messages.extend(
                    self.database.get_messages_since(chat_id=message.chat_id, since=self.context_window)
                )

                # Make LLM request
                llm_response = self.llm.generate_response(
                    prompt=generate_prompt(
                        members=self.database.get_members(chat_id=message.chat_id),
                        bot_name=self.name,
                        bot_identity=self.identity
                    ),
                    messages=context_messages
                )
                logger.info(f'llm_response - chat_id: {message.chat_id} - msg_id: {message.id}')
                logger.debug(f'\n{llm_response.model_dump_json(indent=4)}')

                # Send reaction
                if llm_response.reaction and llm_response.reaction_strength >= self.reaction_threshold:
                    await message.set_reaction(llm_response.reaction)
                    logger.info(f'msg_reaction - chat_id: {message.chat_id} - msg_id: {message.id}')

                # Send LLM reply as message
                llm_sent_message = await message.reply_text(
                    sanitize_markdown(llm_response.message), 
                    parse_mode='Markdown'
                )
                logger.info(f'msg_out - chat_id: {message.chat_id} - msg_id: {message.id}')

                with self.database.Session.begin() as session:
                    # Store LLM reply as message
                    if llm_sent_message.from_user:    
                        llm_message_record = Message(
                            id=llm_sent_message.id, 
                            user_id=llm_sent_message.from_user.id, 
                            chat_id=message.chat_id, 
                            text=llm_response.message,
                            created_at=llm_sent_message.date,
                            reply_to_id=message.id
                        )
                        session.add(llm_message_record)
                        logger.info(f'msg_out_persisted - chat_id: {message.chat_id} - msg_id: {message.id}')
        except Exception as e:
            logger.error(f'msg_failed - chat_id: {message.chat_id} - msg_id: {message.id} - error: {e}')

    # -----------------------------------------
    # Edit Text
    # -----------------------------------------

    async def on_edit_text(self, update: Update, context: CallbackContext):
        if update.edited_message is None or update.edited_message.text is None:
            return

        with self.database.Session.begin() as session:
            message_id, message_text = update.edited_message.message_id, update.edited_message.text
            message = session.query(Message).filter(Message.id == message_id).one()
            message.text = message_text

    # -----------------------------------------
    # Photo
    # -----------------------------------------

    async def on_photo(self, update: Update, context: CallbackContext):
        if update.message is None or update.message.from_user is None:
            return
        
        message, from_user, caption = update.message, update.message.from_user, update.message.caption

        # Ensure user access has been approved
        user = await self._ensure_access(telegram_user=from_user)
        if user is None:
            return

        bot_mentioned = caption and self.name.lower() in caption.lower()
        is_private_chat = message.chat.type == "private"
        is_reply_to_bot = False
        reply_to_id = None 
        if message.reply_to_message and message.reply_to_message.from_user:
            is_reply_to_bot = message.reply_to_message.from_user.id == self.id
            reply_to_id = message.reply_to_message.id

        try:
            # Conditions to ask OpenAI for a reply
            if bot_mentioned or is_private_chat or is_reply_to_bot:
                await context.bot.send_chat_action(message.chat_id, action=ChatAction.UPLOAD_PHOTO)

            # Last photo is the highest resolution
            photo_file: File = await update.message.photo[-1].get_file()

            # Download photo
            image_path = self.images_path / f"{message.chat_id}-{message.id}.jpg"
            await photo_file.download_to_drive(image_path)

            # Convert to base64 for OpenAI
            with open(image_path, "rb") as image:
                base64_image = base64.b64encode(image.read()).decode('utf-8')

            # OpenAI Vision
            vision_response = self.vision.analyze(
                base64_image=base64_image, 
                prompt="Give a detailed description of this image. Including identification of any people or locations."
            )

            with self.database.Session.begin() as session:
                # Store a text message of computer vision output
                new_message = Message(
                    id=message.id, 
                    user_id=from_user.id, 
                    chat_id=message.chat_id, 
                    text=f'sent an image with caption: "{caption}", image description: "{vision_response}"',
                    created_at=message.date,
                    image_path=str(image_path),
                    reply_to_id=reply_to_id
                )
                session.add(new_message)

            # Conditions to ask LLM for a reply
            if bot_mentioned or is_private_chat or is_reply_to_bot:
                await context.bot.send_chat_action(message.chat_id, action=ChatAction.TYPING)

                # Make LLM request
                llm_response = self.llm.generate_response(
                    prompt=generate_prompt(
                        members=self.database.get_members(chat_id=message.chat_id),
                        bot_name=self.name,
                        bot_identity=self.identity
                    ),
                    messages=self.database.get_messages_since(chat_id=message.chat_id, since=timedelta(hours=12))
                )
                logger.info(f'\n{llm_response.model_dump_json(indent=4)}')

                # Send reaction
                if llm_response.reaction and llm_response.reaction_strength >= self.reaction_threshold:
                    await message.set_reaction(llm_response.reaction)

                # Send LLM reply as message
                llm_sent_message = await message.reply_text(
                    sanitize_markdown(llm_response.message), 
                    parse_mode='Markdown'
                )

                # Store LLM reply as message
                if llm_sent_message.from_user:
                    with self.database.Session.begin() as session:
                        llm_message_record = Message(
                        id=llm_sent_message.id, 
                        user_id=llm_sent_message.from_user.id, 
                        chat_id=message.chat_id, 
                        text=llm_response.message,
                        created_at=llm_sent_message.date,
                        reply_to_id=message.id
                    )
                    session.add(llm_message_record)
        except Exception as e:
            logger.error(f'msg_failed - chat_id: {message.chat_id} - msg_id: {message.id} - error: {e}')

    # -----------------------------------------
    # Callback
    # -----------------------------------------

    async def on_callback(self, update: Update, context: CallbackContext):
        if update.callback_query is None or update.callback_query.data is None or update.callback_query.message is None:
            return

        if update.callback_query.data.startswith(ACCESS_APPROVE_PREFIX):
            session = self.database.Session()
            args = update.callback_query.data.split(ACCESS_DELIMITER)
            user_id = args[1]

            # User approved, save to the database
            user = User(id=user_id)
            session.add(user)

            try:
                session.commit()
            except Exception as e:
                session.rollback()
                logger.error(f"Failed to store approved user: {user_id}, error: {str(e)}")
            finally:
                session.close()

            # Notify admin
            if isinstance(update.callback_query.message, TelegramMessage):
                await update.callback_query.message.reply_text(f"Approved.")
        elif update.callback_query.data.startswith(ACCESS_DENY_PREFIX):
            args = update.callback_query.data.split(ACCESS_DELIMITER)
            user_id = args[1]

            # Notify admin
            if isinstance(update.callback_query.message, TelegramMessage):
                await update.callback_query.message.reply_text(f"User with ID {user_id} was denied.")

        # Acknowledge the callback query
        await update.callback_query.answer()

    async def _ensure_access(self, telegram_user: TelegramUser) -> User | None:
        with self.database.Session.begin() as session:
            user = session.query(User).filter_by(id=telegram_user.id).first()
            if user:
                # Store metadata as approval only stores id
                user.first_name = telegram_user.first_name
                user.last_name = telegram_user.last_name
                user.username = telegram_user.username
                return user

        # Create approval request with Yes/No buttons
        keyboard = [
            [
                InlineKeyboardButton("Yes", callback_data=f'{ACCESS_APPROVE_PREFIX}{ACCESS_DELIMITER}{telegram_user.id}'),
                InlineKeyboardButton("No", callback_data=f'{ACCESS_DENY_PREFIX}{ACCESS_DELIMITER}{telegram_user.id}')
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Send the approval request to your personal account
        await self.telegram.bot.send_message(
            chat_id=self.admin_user_id,
            text=f"Approve {telegram_user.first_name} {telegram_user.last_name} ({telegram_user.username})) to use the bot?",
            reply_markup=reply_markup
        )

        return None
