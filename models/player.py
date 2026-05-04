import datetime

from sqlalchemy import BigInteger, Boolean, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class Player(Base):
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(primary_key=True)
    discord_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    discord_username: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    last_active_at: Mapped[datetime.datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False)

    characters: Mapped[list["Character"]] = relationship(  # noqa: F821
        "Character", back_populates="player", cascade="all, delete-orphan"
    )
