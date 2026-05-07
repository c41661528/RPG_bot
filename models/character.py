import datetime
import enum
from typing import Any

from sqlalchemy import BigInteger, Boolean, Enum, ForeignKey, Integer, SmallInteger, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class ClassType(str, enum.Enum):
    STREET_SAMURAI = "street_samurai"
    NETRUNNER = "netrunner"
    SCAVENGER = "scavenger"


class Character(Base):
    __tablename__ = "characters"

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(50))
    class_type: Mapped[ClassType] = mapped_column(Enum(ClassType, name="class_type_enum"))

    # ── Progression ─────────────────────────────────────────────
    level: Mapped[int] = mapped_column(SmallInteger, default=1)
    exp: Mapped[int] = mapped_column(Integer, default=0)
    rebirth_count: Mapped[int] = mapped_column(SmallInteger, default=0)
    # e.g. {"vitality": 2, "reflex": 1} — permanent bonuses after rebirth
    rebirth_bonus: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    # ── Economy ──────────────────────────────────────────────────
    credits: Mapped[int] = mapped_column(BigInteger, default=0)
    energy_cells: Mapped[int] = mapped_column(Integer, default=0)
    medkits: Mapped[int] = mapped_column(Integer, default=0)
    consumables: Mapped[dict] = mapped_column(JSONB, default=dict)
    # custom_items = {item_id: stats_dict} for randomly generated shop equipment
    custom_items: Mapped[dict] = mapped_column(JSONB, default=dict)
    # shop_stock = {"gen_level": N, "items": [{"item_id": str, "price": int}]}
    shop_stock: Mapped[dict] = mapped_column(JSONB, default=dict)

    # ── Equipment ────────────────────────────────────────────────
    # inventory = list of unequipped item_id strings, max 20
    inventory: Mapped[list] = mapped_column(JSONB, default=list)
    equipped_weapon:    Mapped[str | None] = mapped_column(String(60), nullable=True, default=None)
    equipped_armor:     Mapped[str | None] = mapped_column(String(60), nullable=True, default=None)
    equipped_helmet:    Mapped[str | None] = mapped_column(String(60), nullable=True, default=None)
    equipped_accessory: Mapped[str | None] = mapped_column(String(60), nullable=True, default=None)
    # item_enhancements = {item_id: enhance_level} — shared across bag & equipped
    item_enhancements: Mapped[dict] = mapped_column(JSONB, default=dict)
    # materials = {material_id: count}
    materials: Mapped[dict] = mapped_column(JSONB, default=dict)

    # ── Quests ───────────────────────────────────────────────────
    # {"date": "YYYY-MM-DD", "quests": [...]}
    quests: Mapped[dict] = mapped_column(JSONB, default=dict)
    # {"week": "YYYY-WW", "quests": [...]}
    weekly_quests: Mapped[dict] = mapped_column(JSONB, default=dict)

    # ── Achievements ─────────────────────────────────────────────
    # {achievement_id: True}
    achievements: Mapped[dict] = mapped_column(JSONB, default=dict)

    # ── Titles ───────────────────────────────────────────────────
    equipped_title:  Mapped[str | None] = mapped_column(String(60), nullable=True, default=None)
    # {title_id: True}  +  internal counters: __crafted_once__, __craft_count__
    unlocked_titles: Mapped[dict]       = mapped_column(JSONB, default=dict)

    # ── PvP ──────────────────────────────────────────────────────
    # {"wins": int, "losses": int, "last_duel_at": iso, "duels_today": int, "duels_date": str}
    pvp_stats: Mapped[dict] = mapped_column(JSONB, default=dict)

    # ── Dungeon ──────────────────────────────────────────────────
    # {"dungeon_id": str, "floor": int, "hp": int, "energy": int,
    #  "exp_earned": int, "credits_earned": int, "active": bool}
    dungeon_state: Mapped[dict] = mapped_column(JSONB, default=dict)

    # ── Base stats ───────────────────────────────────────────────
    stat_vitality: Mapped[int] = mapped_column(SmallInteger)
    stat_reflex: Mapped[int] = mapped_column(SmallInteger)
    stat_tech: Mapped[int] = mapped_column(SmallInteger)
    stat_points_avail: Mapped[int] = mapped_column(SmallInteger, default=0)

    # ── Combat stats ─────────────────────────────────────────────
    hp_current: Mapped[int] = mapped_column(Integer)
    hp_max: Mapped[int] = mapped_column(Integer)
    energy_current: Mapped[int] = mapped_column(Integer)
    energy_max: Mapped[int] = mapped_column(Integer)

    # ── Statistics ───────────────────────────────────────────────
    kills: Mapped[int] = mapped_column(Integer, default=0)

    # ── World state ──────────────────────────────────────────────
    current_location: Mapped[str] = mapped_column(String(80), default="廢墟東區")
    is_in_combat: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())

    player: Mapped["Player"] = relationship("Player", back_populates="characters")  # noqa: F821
