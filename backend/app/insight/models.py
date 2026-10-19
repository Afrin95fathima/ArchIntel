from sqlalchemy import JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base
from app.models import Identity


class AssistantMessage(Identity, Base):
    """Conversation memory per principal and analysis (= application version). Stores the full text so every
    prompt, tool call and answer can be reviewed; the tamper-evident audit log records content-free events."""
    __tablename__ = 'assistant_messages'
    analysis_id: Mapped[str] = mapped_column(String(36), index=True)
    application_id: Mapped[str] = mapped_column(String(36), default='')
    principal_id: Mapped[str] = mapped_column(String(36), index=True)
    turn_id: Mapped[str] = mapped_column(String(36), index=True)
    role: Mapped[str] = mapped_column(String(12))              # user | tool | assistant
    content: Mapped[str] = mapped_column(Text, default='')
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
