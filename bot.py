import asyncio
import base64
from datetime import timedelta
from functools import partial
import json
import logging
import os
import sys
import uuid
import logging
from pathlib import Path
import time
from typing import Any, cast
from telegram import (
    File, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup, 
    Message as TelegramMessage, 
    Update, 
    User as TelegramUser
)
from telegram.constants import ChatAction
from telegram.error import BadRequest, RetryAfter
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
from video.client import VideoClient

ACCESS_APPROVE_PREFIX = 'approve'
ACCESS_DENY_PREFIX = 'deny'
ACCESS_DELIMITER = '_'
MODIFY_APPROVE_PREFIX = 'mod_approve'
MODIFY_DENY_PREFIX = 'mod_deny'

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
        video: VideoClient,
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
        self.llm = llm
        self.vision = vision
        self.video = video
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

        # Check for hot-reload state
        reload_file = self.images_path.parent / "reload_state.json"
        if reload_file.exists():
            try:
                with open(reload_file, "r") as f:
                    state = json.load(f)
                
                chat_id = state.get("chat_id")
                reply_to_message_id = state.get("reply_to_message_id")
                message_text = state.get("message")
                
                if chat_id and message_text:
                    await self.telegram.bot.send_message(
                        chat_id=chat_id,
                        text=message_text,
                        reply_to_message_id=reply_to_message_id
                    )
            except Exception as e:
                logger.error(f"Failed to process reload state: {e}")
            finally:
                try:
                    os.remove(reload_file)
                except OSError:
                    pass

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

            bot_mentioned = self.name.lower() in text.lower() or self.username in text
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

                # Code Modification Request
                await self._handle_modification_request(llm_response, message, from_user)

                # Generate video (Tool Call)
                if llm_response.video_prompt:
                    await context.bot.send_chat_action(message.chat_id, action=ChatAction.UPLOAD_VIDEO)
                    
                    # Check for image input (reply to photo)
                    image_path = None
                    if message.reply_to_message and message.reply_to_message.photo:
                        photo_file = await message.reply_to_message.photo[-1].get_file()
                        image_path = self.images_path / f"{message.chat_id}-{message.reply_to_message.id}.jpg"
                        # Only download if not already exists (optimization) or just overwrite
                        if not image_path.exists():
                            await photo_file.download_to_drive(image_path)
                    
                    try:
                        video_path = self.video.generate_video(
                            prompt=text,
                            image_path=str(image_path) if image_path is not None else None,
                        )
                        try:
                            await message.reply_video(video=open(video_path, 'rb'))
                        except Exception as e:
                            logger.error(f"Video generation failed 2: {e}")
                            await message.reply_text(f"Video generation failed 2: {e}")
                    except Exception as e:
                        logger.error(f"Video generation failed: {e}")
                        await message.reply_text(f"Video generation failed: {e}")

                # Send reaction
                if llm_response.reaction and llm_response.reaction_strength >= self.reaction_threshold:
                    await message.set_reaction(llm_response.reaction)
                    logger.info(f'msg_reaction - chat_id: {message.chat_id} - msg_id: {message.id}')

                # Send LLM reply as message
                try:
                    llm_sent_message = await message.reply_text(
                        sanitize_markdown(llm_response.message), 
                        parse_mode='Markdown'
                    )
                except Exception:
                    llm_sent_message = await message.reply_text(llm_response.message)
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

        bot_mentioned = caption and (self.name.lower() in caption.lower() or self.username in caption)
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

                # Code Modification Request
                await self._handle_modification_request(llm_response, message, from_user)

                # Generate video (Tool Call)
                if llm_response.video_prompt and caption:
                    await context.bot.send_chat_action(message.chat_id, action=ChatAction.UPLOAD_VIDEO)
                    
                    try:
                        # Use the current image as input
                        video_path = self.video.generate_video(prompt=caption, image_path=str(image_path))
                        await message.reply_video(video=open(video_path, 'rb'))
                    except Exception as e:
                        logger.error(f"Video generation failed: {e}")
                        await message.reply_text(f"Video generation failed: {e}")

                # Send reaction
                if llm_response.reaction and llm_response.reaction_strength >= self.reaction_threshold:
                    await message.set_reaction(llm_response.reaction)

                # Send LLM reply as message
                try:
                    llm_sent_message = await message.reply_text(
                        sanitize_markdown(llm_response.message), 
                        parse_mode='Markdown'
                    )
                except Exception:
                    llm_sent_message = await message.reply_text(llm_response.message)

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
                
        elif update.callback_query.data.startswith(MODIFY_APPROVE_PREFIX):
            args = update.callback_query.data.split(ACCESS_DELIMITER)
            request_id = args[1]
            
            pending_file = self.images_path.parent / "pending_modifications.json"
            pending = {}
            if pending_file.exists():
                with open(pending_file, "r") as f:
                    try:
                        pending = json.load(f)
                    except json.JSONDecodeError:
                        pass
                        
            request_data = pending.get(request_id)
            if not request_data:
                if isinstance(update.callback_query.message, TelegramMessage):
                    await update.callback_query.message.reply_text("Modification request not found or already processed.")
            else:
                if isinstance(update.callback_query.message, TelegramMessage):
                    await update.callback_query.message.reply_text("Modification approved. Executing...")
                
                # Execute in background so we don't block the callback query
                asyncio.create_task(self._execute_modification(request_data, update.callback_query.message))
                
        elif update.callback_query.data.startswith(MODIFY_DENY_PREFIX):
            if isinstance(update.callback_query.message, TelegramMessage):
                await update.callback_query.message.reply_text("Modification request denied.")

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

    async def _handle_modification_request(self, llm_response, message, from_user):
        if not getattr(llm_response, "modification_prompt", None):
            return False

        request_id = str(uuid.uuid4())
        
        pending_file = self.images_path.parent / "pending_modifications.json"
        pending = {}
        if pending_file.exists():
            with open(pending_file, "r") as f:
                try:
                    pending = json.load(f)
                except json.JSONDecodeError:
                    pass
        
        pending[request_id] = {
            "chat_id": message.chat_id,
            "reply_to_message_id": message.id,
            "prompt": llm_response.modification_prompt
        }
        with open(pending_file, "w") as f:
            json.dump(pending, f)
        
        keyboard = [
            [
                InlineKeyboardButton("Approve", callback_data=f'{MODIFY_APPROVE_PREFIX}{ACCESS_DELIMITER}{request_id}'),
                InlineKeyboardButton("Deny", callback_data=f'{MODIFY_DENY_PREFIX}{ACCESS_DELIMITER}{request_id}')
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            await self.telegram.bot.send_message(
                chat_id=self.admin_user_id,
                text=f"Code modification requested by {from_user.first_name}:\n\n{llm_response.modification_prompt}\n\nApprove execution?",
                reply_markup=reply_markup
            )
            await message.reply_text("I have requested admin approval to make this code change.")
        except Exception as e:
            logger.error(f"Failed to send modification request: {e}")
            
        return True

    async def _execute_modification(self, request_data, message):
        from google_antigravity import LocalAgentConfig, Agent
        
        # We need the parent directory of 'bots/folder_name' to get the workspace root
        workspace_dir = str(self.images_path.parent.parent.parent)
        
        config = LocalAgentConfig(
            workspace=workspace_dir,
            instructions="You are an expert Python developer modifying a Telegram bot. Fulfill the user's request. Modify the files directly."
        )
        agent = Agent(config)
        
        try:
            await asyncio.to_thread(agent.run, task=request_data["prompt"])
            
            # Auto-commit the changes
            import subprocess
            try:
                commit_message = f"Auto-modification: {request_data['prompt'][:50]}..."
                subprocess.run(["git", "add", "."], cwd=workspace_dir, check=True)
                subprocess.run(["git", "commit", "-m", commit_message], cwd=workspace_dir, check=True)
            except subprocess.CalledProcessError as e:
                logger.error(f"Failed to commit changes: {e}")
            
            reload_file = self.images_path.parent / "reload_state.json"
            with open(reload_file, "w") as f:
                json.dump({
                    "chat_id": request_data["chat_id"],
                    "reply_to_message_id": request_data["reply_to_message_id"],
                    "message": "I have successfully modified my code and restarted! Let me know if the changes look good."
                }, f)
                
            if isinstance(message, TelegramMessage):
                await message.reply_text("Execution complete. Restarting bot...")
                
            os.execv(sys.executable, ['python'] + sys.argv)
            
        except Exception as e:
            logger.error(f"Agent execution failed: {e}")
            if isinstance(message, TelegramMessage):
                await message.reply_text(f"Agent execution failed: {e}")
