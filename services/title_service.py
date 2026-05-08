"""
Title system — cosmetic + bonus titles unlocked through play.

Each title has unlock conditions and (optionally) passive bonuses.
Bonus keys: atk_pct, def_pct, hp_pct, crit_bonus, credits_pct, exp_pct,
            dungeon_reward_pct, craft_success_pct.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.orm.attributes import flag_modified

if TYPE_CHECKING:
    from models.character import Character


# Discord ID of the bot creator — gets the exclusive 創世者-宅宅 title.
CREATOR_DISCORD_ID = 1325263341937229906


_TITLES: list[dict] = [
    # ── Creator (exclusive) ──────────────────────────────────────
    {
        "id": "creator_t", "name": "創世者-宅宅", "emoji": "🌌",
        "desc": "廢土的創世者本人，全屬性 +10%、暴擊 +5%、信用點/EXP +10%。",
        "rarity": 4,
        "bonuses": {
            "atk_pct": 0.10, "def_pct": 0.10, "hp_pct": 0.10,
            "crit_bonus": 0.05, "credits_pct": 0.10, "exp_pct": 0.10,
        },
        "unlock": lambda c: bool((c.unlocked_titles or {}).get("__creator__")),
    },
    # ── Default ──────────────────────────────────────────────────
    {
        "id": "wasteland_rookie", "name": "新手廢土客", "emoji": "🌅",
        "desc": "預設稱號，所有人皆持有。",
        "rarity": 1, "bonuses": {},
        "unlock": lambda c: True,
    },
    # ── Kills ────────────────────────────────────────────────────
    {
        "id": "first_blood_t", "name": "初次見血者", "emoji": "🔴",
        "desc": "擊殺第一隻敵人。",
        "rarity": 1, "bonuses": {},
        "unlock": lambda c: c.kills >= 1,
    },
    {
        "id": "veteran_t", "name": "百戰老兵", "emoji": "🏅",
        "desc": "擊殺 100 隻敵人，ATK +3%。",
        "rarity": 2, "bonuses": {"atk_pct": 0.03},
        "unlock": lambda c: c.kills >= 100,
    },
    {
        "id": "war_machine_t", "name": "戰爭機器", "emoji": "💀",
        "desc": "擊殺 500 隻敵人，ATK +6%。",
        "rarity": 3, "bonuses": {"atk_pct": 0.06},
        "unlock": lambda c: c.kills >= 500,
    },
    # ── Level ────────────────────────────────────────────────────
    {
        "id": "survivor_t", "name": "廢土倖存者", "emoji": "🌱",
        "desc": "達到 Lv.10，HP +3%。",
        "rarity": 1, "bonuses": {"hp_pct": 0.03},
        "unlock": lambda c: c.level >= 10,
    },
    {
        "id": "elite_t", "name": "菁英戰士", "emoji": "⭐",
        "desc": "達到 Lv.25，全屬性 +2%。",
        "rarity": 2, "bonuses": {"atk_pct": 0.02, "def_pct": 0.02, "hp_pct": 0.02},
        "unlock": lambda c: c.level >= 25,
    },
    {
        "id": "legend_t", "name": "傳奇人物", "emoji": "🌟",
        "desc": "達到 Lv.50，全屬性 +5%、暴擊 +3%。",
        "rarity": 4,
        "bonuses": {"atk_pct": 0.05, "def_pct": 0.05, "hp_pct": 0.05, "crit_bonus": 0.03},
        "unlock": lambda c: c.level >= 50,
    },
    # ── Wealth ───────────────────────────────────────────────────
    {
        "id": "street_rich_t", "name": "街頭暴發戶", "emoji": "💰",
        "desc": "持有 10,000 信用點，獲得信用點 +5%。",
        "rarity": 2, "bonuses": {"credits_pct": 0.05},
        "unlock": lambda c: c.credits >= 10_000,
    },
    {
        "id": "mogul_t", "name": "廢土大亨", "emoji": "💎",
        "desc": "持有 100,000 信用點，獲得信用點 +12%。",
        "rarity": 3, "bonuses": {"credits_pct": 0.12},
        "unlock": lambda c: c.credits >= 100_000,
    },
    # ── Rebirth ──────────────────────────────────────────────────
    {
        "id": "reborn_t", "name": "涅槃者", "emoji": "🔁",
        "desc": "完成首次轉生，EXP +5%。",
        "rarity": 3, "bonuses": {"exp_pct": 0.05},
        "unlock": lambda c: c.rebirth_count >= 1,
    },
    {
        "id": "transcendent_t", "name": "超越者", "emoji": "🔮",
        "desc": "完成 5 次轉生，EXP/信用點 +15%。",
        "rarity": 4, "bonuses": {"exp_pct": 0.15, "credits_pct": 0.15},
        "unlock": lambda c: c.rebirth_count >= 5,
    },
    # ── Dungeon ──────────────────────────────────────────────────
    {
        "id": "dungeon_master_t", "name": "迷宮霸主", "emoji": "👑",
        "desc": "通關所有 3 座迷宮，迷宮獎勵 +20%。",
        "rarity": 4, "bonuses": {"dungeon_reward_pct": 0.20},
        "unlock": lambda c: bool((c.achievements or {}).get("dungeon_master", False)),
    },
    # ── PvP ──────────────────────────────────────────────────────
    {
        "id": "pvp_rookie_t", "name": "決鬥新星", "emoji": "⚔️",
        "desc": "贏得首場決鬥。",
        "rarity": 1, "bonuses": {},
        "unlock": lambda c: (c.pvp_stats or {}).get("wins", 0) >= 1,
    },
    {
        "id": "pvp_master_t", "name": "決鬥大師", "emoji": "🏆",
        "desc": "贏得 10 場決鬥，ATK +4%。",
        "rarity": 3, "bonuses": {"atk_pct": 0.04},
        "unlock": lambda c: (c.pvp_stats or {}).get("wins", 0) >= 10,
    },
    {
        "id": "pvp_king_t", "name": "決鬥之王", "emoji": "👑",
        "desc": "贏得 50 場決鬥，全屬性 +5%。",
        "rarity": 4, "bonuses": {"atk_pct": 0.05, "def_pct": 0.05, "hp_pct": 0.05},
        "unlock": lambda c: (c.pvp_stats or {}).get("wins", 0) >= 50,
    },
    # ── Crafting ─────────────────────────────────────────────────
    {
        "id": "smith_apprentice_t", "name": "鍛造學徒", "emoji": "🔨",
        "desc": "完成首次合成。",
        "rarity": 1, "bonuses": {},
        "unlock": lambda c: bool((c.unlocked_titles or {}).get("__crafted_once__", False)),
    },
    {
        "id": "smith_master_t", "name": "鍛造大師", "emoji": "⚒️",
        "desc": "完成 30 次合成，合成成功率 +5%。",
        "rarity": 3, "bonuses": {"craft_success_pct": 0.05},
        "unlock": lambda c: (c.unlocked_titles or {}).get("__craft_count__", 0) >= 30,
    },
]

_TITLE_MAP: dict[str, dict] = {t["id"]: t for t in _TITLES}
_RARITY_EMOJI = {1: "⚪", 2: "🟢", 3: "🔵", 4: "🟣"}


# ── Public API ────────────────────────────────────────────────────

def all_titles() -> list[dict]:
    return _TITLES


def get_title(title_id: str) -> dict | None:
    return _TITLE_MAP.get(title_id)


def is_unlocked(char: Character, title_id: str) -> bool:
    """Return True if the title is unlocked for the character."""
    t = _TITLE_MAP.get(title_id)
    if not t:
        return False
    if (char.unlocked_titles or {}).get(title_id):
        return True
    try:
        return bool(t["unlock"](char))
    except Exception:
        return False


def check_title_unlocks(char: Character, discord_id: int | None = None) -> list[str]:
    """Evaluate every title; persist newly earned ones. Returns names list.

    Pass `discord_id` (the player's Discord ID) so creator-exclusive titles
    can be granted. Call inside an open DB session, then commit afterward.
    """
    unlocked = dict(char.unlocked_titles or {})
    changed  = False

    # Mark the internal creator flag so the creator_t lambda evaluates True.
    if discord_id == CREATOR_DISCORD_ID and not unlocked.get("__creator__"):
        unlocked["__creator__"] = True
        char.unlocked_titles    = unlocked
        flag_modified(char, "unlocked_titles")
        changed = True

    newly: list[str] = []
    for t in _TITLES:
        if unlocked.get(t["id"]):
            continue
        try:
            earned = bool(t["unlock"](char))
        except Exception:
            earned = False
        if earned:
            unlocked[t["id"]] = True
            newly.append(t["name"])
            changed = True

    if changed:
        char.unlocked_titles = unlocked
        flag_modified(char, "unlocked_titles")
    return newly


def equipped_title_data(char: Character) -> dict:
    """Return the title dict for the equipped title (falls back to default)."""
    if char.equipped_title:
        t = _TITLE_MAP.get(char.equipped_title)
        if t and is_unlocked(char, char.equipped_title):
            return t
    return _TITLE_MAP["wasteland_rookie"]


def title_bonuses(char: Character) -> dict:
    """Return the bonus dict for the equipped title (or empty)."""
    return equipped_title_data(char).get("bonuses", {})


def rarity_emoji(rarity: int) -> str:
    return _RARITY_EMOJI.get(rarity, "⚪")


def increment_craft_count(char: Character) -> None:
    """Track crafting progression for craft titles."""
    titles = dict(char.unlocked_titles or {})
    titles["__crafted_once__"] = True
    titles["__craft_count__"] = titles.get("__craft_count__", 0) + 1
    char.unlocked_titles = titles
    flag_modified(char, "unlocked_titles")
