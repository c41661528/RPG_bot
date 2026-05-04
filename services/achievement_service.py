"""
Achievement definitions and unlock logic.

All checks are synchronous; call check_achievements() inside an open DB session
and commit the session afterward.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.orm.attributes import flag_modified

if TYPE_CHECKING:
    from models.character import Character

# ── Achievement definitions ──────────────────────────────────────
# Each entry: {"id", "name", "emoji", "desc", "check_fn"}
# check_fn(char) → bool  (True = should unlock)

_ACHIEVEMENTS: list[dict] = [
    # ── Kills ─────────────────────────────────────────────────────
    {
        "id":    "first_blood",
        "name":  "初次見血",
        "emoji": "🔴",
        "desc":  "擊殺第一隻敵人。",
        "check_fn": lambda c: c.kills >= 1,
    },
    {
        "id":    "veteran",
        "name":  "百戰老兵",
        "emoji": "🏅",
        "desc":  "累計擊殺 100 隻敵人。",
        "check_fn": lambda c: c.kills >= 100,
    },
    {
        "id":    "war_machine",
        "name":  "戰爭機器",
        "emoji": "💀",
        "desc":  "累計擊殺 500 隻敵人。",
        "check_fn": lambda c: c.kills >= 500,
    },
    # ── Level ─────────────────────────────────────────────────────
    {
        "id":    "survivor",
        "name":  "廢土倖存者",
        "emoji": "🌱",
        "desc":  "達到 Lv.10。",
        "check_fn": lambda c: c.level >= 10,
    },
    {
        "id":    "elite",
        "name":  "菁英戰士",
        "emoji": "⭐",
        "desc":  "達到 Lv.25。",
        "check_fn": lambda c: c.level >= 25,
    },
    {
        "id":    "legend",
        "name":  "傳奇人物",
        "emoji": "🌟",
        "desc":  "達到 Lv.50（最高等級）。",
        "check_fn": lambda c: c.level >= 50,
    },
    # ── Credits ───────────────────────────────────────────────────
    {
        "id":    "street_rich",
        "name":  "街頭暴發戶",
        "emoji": "💰",
        "desc":  "持有 10,000 信用點。",
        "check_fn": lambda c: c.credits >= 10_000,
    },
    {
        "id":    "mogul",
        "name":  "廢土大亨",
        "emoji": "💎",
        "desc":  "持有 100,000 信用點。",
        "check_fn": lambda c: c.credits >= 100_000,
    },
    # ── Rebirth ───────────────────────────────────────────────────
    {
        "id":    "reborn",
        "name":  "涅槃重生",
        "emoji": "🔁",
        "desc":  "完成第一次轉生。",
        "check_fn": lambda c: c.rebirth_count >= 1,
    },
    {
        "id":    "transcendent",
        "name":  "超越人體極限",
        "emoji": "🔮",
        "desc":  "完成 5 次轉生（上限）。",
        "check_fn": lambda c: c.rebirth_count >= 5,
    },
    # ── Equipment ─────────────────────────────────────────────────
    {
        "id":    "fully_armed",
        "name":  "全副武裝",
        "emoji": "🛡️",
        "desc":  "同時裝備武器、護甲、頭盔與配件。",
        "check_fn": lambda c: bool(c.equipped_weapon and c.equipped_armor
                                    and c.equipped_helmet and c.equipped_accessory),
    },
    {
        "id":    "max_enhanced",
        "name":  "極限強化",
        "emoji": "🔨",
        "desc":  "將任意裝備強化至 +5。",
        "check_fn": lambda c: any(v >= 5 for v in (c.item_enhancements or {}).values()),
    },
    # ── Dungeon ───────────────────────────────────────────────────
    {
        "id":    "dungeon_clearer",
        "name":  "迷宮探索者",
        "emoji": "🗺️",
        "desc":  "首次通關任意迷宮全 5 層。",
        "check_fn": lambda c: c.achievements.get("dungeon_clearer", False),
    },
    {
        "id":    "dungeon_master",
        "name":  "迷宮霸主",
        "emoji": "👑",
        "desc":  "通關所有 3 座迷宮。",
        "check_fn": lambda c: c.achievements.get("dungeon_master", False),
    },
    # ── Quests ────────────────────────────────────────────────────
    {
        "id":    "quest_starter",
        "name":  "接令者",
        "emoji": "📋",
        "desc":  "完成第一個每日任務。",
        "check_fn": lambda c: c.achievements.get("quest_starter", False),
    },
    {
        "id":    "weekly_hero",
        "name":  "週常英雄",
        "emoji": "📅",
        "desc":  "完成一組週常任務（全 3 個）。",
        "check_fn": lambda c: c.achievements.get("weekly_hero", False),
    },
]

_ACHIEVEMENT_MAP: dict[str, dict] = {a["id"]: a for a in _ACHIEVEMENTS}


def all_achievements() -> list[dict]:
    return _ACHIEVEMENTS


def check_achievements(char: Character) -> list[str]:
    """
    Check all unlockable achievements. Unlocks any that are newly earned.
    Returns list of newly unlocked achievement names.
    Call inside an open DB session and commit afterward.
    """
    achs = dict(char.achievements or {})
    newly_unlocked: list[str] = []

    for ach in _ACHIEVEMENTS:
        if achs.get(ach["id"]):
            continue  # already unlocked
        try:
            earned = ach["check_fn"](char)
        except Exception:
            earned = False
        if earned:
            achs[ach["id"]] = True
            newly_unlocked.append(ach["name"])

    if newly_unlocked:
        char.achievements = achs
        flag_modified(char, "achievements")

    return newly_unlocked


def unlock_achievement(char: Character, ach_id: str) -> bool:
    """Manually unlock an achievement by id. Returns True if it was newly unlocked."""
    achs = dict(char.achievements or {})
    if achs.get(ach_id):
        return False
    achs[ach_id] = True
    char.achievements = achs
    flag_modified(char, "achievements")
    return True
