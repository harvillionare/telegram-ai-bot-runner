from datetime import datetime, timedelta, timezone
from pathlib import Path
from sqlalchemy import BigInteger, create_engine, DateTime, ForeignKey, ForeignKeyConstraint, select, String, Text
from sqlalchemy.orm import declarative_base, Mapped, mapped_column, relationship, sessionmaker
from typing import Set

from logger import logger

Base = declarative_base()

# -----------------------------------------
# User
# -----------------------------------------

class User(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    messages = relationship("Message", back_populates="user")

    def __init__(self, id, first_name: str | None = None, last_name: str | None = None, username: str | None = None):
        self.id = id
        self.first_name = first_name
        self.last_name = last_name
        self.username = username

# -----------------------------------------
# Message
# -----------------------------------------

class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    text: Mapped[str] = mapped_column(Text, nullable=False)
    image_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reply_to_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        ForeignKeyConstraint(
            ['reply_to_id', 'chat_id'],
            ['messages.id', 'messages.chat_id'],
            name='fk_reply_to'
        ),
    )

    # Relationship with User
    user = relationship("User", back_populates="messages")

    # Relationship to the referenced message
    reply_to_message = relationship(
        "Message",
        remote_side=[id, chat_id],
        backref="replying_messages"
    )

    def __init__(
        self, 
        id: int, 
        chat_id: int, 
        user_id: int, 
        text: str, 
        created_at: datetime,
        image_path: str | None = None, 
        reply_to_id: int | None = None
    ):
        self.id = id
        self.chat_id = chat_id
        self.user_id = user_id
        self.text = text
        self.created_at = created_at
        self.image_path = image_path
        self.reply_to_id = reply_to_id        

# -----------------------------------------
# Database
# -----------------------------------------

class Database:

    # Initialization
    # -----------------------------------------

    def __init__(self, path: Path, admin_user_id: int, bot_id: int, bot_name: str, bot_username: str):
        self._engine = create_engine(f"sqlite:///{path / 'bot.db'}", future=True)
        self.Session = sessionmaker(bind=self._engine, future=True)
        self._create_tables_if_needed()
        self._create_indexes_if_needed()
        self._create_admin_user_if_needed(admin_user_id=admin_user_id)
        self._create_bot_user_if_needed(bot_id=bot_id, bot_name=bot_name, bot_username=bot_username)

    def _create_indexes_if_needed(self):
        with self._engine.begin() as conn:
            conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS messages_chat_id_idx ON messages(chat_id)")

    def _create_tables_if_needed(self):
        Base.metadata.create_all(bind=self._engine)

    def _create_admin_user_if_needed(self, admin_user_id: int):
        session = self.Session()
        try:
            user = session.query(User).filter_by(id=admin_user_id).first()
            if user is None:
                session.add(User(id=admin_user_id))
                session.commit()
                logger.info("Admin user has been created")
        except Exception as e:
            session.rollback()
            logger.error(f"An error occurred: {str(e)}")
        finally:
            session.close()

    def _create_bot_user_if_needed(self, bot_id: int, bot_name: str, bot_username: str):
        session = self.Session()
        try:
            bot_user = session.query(User).filter_by(id=bot_id).first()
            if bot_user is None:
                session.add(User(id=bot_id, first_name=bot_name, username=bot_username))
                session.commit()
                logger.info("Bot user has been created")
        except Exception as e:
            session.rollback()
            logger.error(f"An error occurred: {str(e)}")
        finally:
            session.close()

    # Data Access
    # -----------------------------------------

    def get_messages_since(self, chat_id: int, since: timedelta) -> list[Message]:
        cutoff = datetime.now(timezone.utc) - since
        with self.Session() as session:
            return list(session.scalars(
                select(Message)
                .where(Message.chat_id == chat_id)
                .where(Message.created_at >= cutoff)
                .order_by(Message.created_at.asc())
            ).all())
        
    def get_messages(self, chat_id: int, message_ids: Set[int]) -> list[Message]:
        with self.Session() as session:
            return list(session.scalars(
                select(Message)
                .where(Message.chat_id == chat_id, Message.id.in_(message_ids))
                .order_by(Message.created_at.asc())
            ).all())

    def get_members(self, chat_id: int) -> list[User]:
        with self.Session() as session:
            return list(session.scalars(
                select(User)
                .join(Message, User.id == Message.user_id)
                .where(Message.chat_id == chat_id)
                .distinct()
            ).all())