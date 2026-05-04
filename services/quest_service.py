"""
Quest generation and progress tracking.

All progress updates are synchronous helpers meant to be called
*inside* an already-open SQLAlchemy async session so the change
is committed together with other DB writes in the same transaction.
"""
from __future__ import annotations

import random
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy.orm.attributes import flag_modified

if TYPE_CHECKING:
    from models.character import Character


def _iso_week(d: date) -> str:
    """Return 'YYYY-WW' string for the given date."""
    iso = d.isocalendar()
    return f"{iso.year}-{iso.week:02d}"

# ── Quest template pool ──────────────────────────────────────────
# target_fn(level) → int   reward_*_fn(level) → int

_TEMPLATES: list[dict] = [
    {
        "type": "kill_enemies",
        "icon": "⚔️",
        "desc_fn":           lambda t:  f"擊殺 {t} 隻敵人",
        "target_fn":         lambda lv: max(3,   3 + lv // 5),
        "reward_exp_fn":     lambda lv: lv * 20  + 50,
        "reward_credits_fn": lambda lv: lv * 25  + 100,
    },
    {
        "type": "explore_times",
        "icon": "🔍",
        "desc_fn":           lambda t:  f"探索 {t} 次",
        "target_fn":         lambda lv: max(2,   2 + lv // 10),
        "reward_exp_fn":     lambda lv: lv * 15  + 40,
        "reward_credits_fn": lambda lv: lv * 20  + 80,
    },
    {
        "type": "earn_credits",
        "icon": "💰",
        "desc_fn":           lambda t:  f"從戰鬥中賺取 {t:,} 信用點",
        "target_fn":         lambda lv: max(100, lv * 80),
        "reward_exp_fn":     lambda lv: lv * 15  + 40,
        "reward_credits_fn": lambda lv: lv * 30  + 100,
    },
    {
        "type": "deal_damage",
        "icon": "💥",
        "desc_fn":           lambda t:  f"造成 {t:,} 點總傷害",
        "target_fn":         lambda lv: max(100, lv * 50),
        "reward_exp_fn":     lambda lv: lv * 20  + 50,
        "reward_credits_fn": lambda lv: lv * 20  + 80,
    },
    {
        "type": "use_skill",
        "icon": "💠",
        "desc_fn":           lambda t:  f"使用技能 {t} 次",
        "target_fn":         lambda lv: max(2,   2 + lv // 10),
        "reward_exp_fn":     lambda lv: lv * 18  + 45,
        "reward_credits_fn": lambda lv: lv * 22  + 90,
    },
    {
        "type": "land_crits",
        "icon": "💢",
        "desc_fn":           lambda t:  f"觸發暴擊 {t} 次",
        "target_fn":         lambda lv: max(3,   2 + lv // 5),
        "reward_exp_fn":     lambda lv: lv * 18  + 45,
        "reward_credits_fn": lambda lv: lv * 22  + 90,
    },
    {
        "type": "loot_equipment",
        "icon": "📦",
        "desc_fn":           lambda t:  f"拾取 {t} 件裝備",
        "target_fn":         lambda lv: max(1,   1 + lv // 10),
        "reward_exp_fn":     lambda lv: lv * 25  + 60,
        "reward_credits_fn": lambda lv: lv * 30  + 120,
    },
    {
        "type": "travel_times",
        "icon": "🗺️",
        "desc_fn":           lambda t:  f"移動地點 {t} 次",
        "target_fn":         lambda lv: 2,
        "reward_exp_fn":     lambda lv: lv * 12  + 30,
        "reward_credits_fn": lambda lv: lv * 15  + 60,
    },
    {
        "type": "use_items_combat",
        "icon": "🩹",
        "desc_fn":           lambda t:  f"在戰鬥中使用道具 {t} 次",
        "target_fn":         lambda lv: max(2,   1 + lv // 10),
        "reward_exp_fn":     lambda lv: lv * 15  + 35,
        "reward_credits_fn": lambda lv: lv * 18  + 70,
    },
    {
        "type": "win_without_items",
        "icon": "🏆",
        "desc_fn":           lambda t:  f"不使用道具贏得 {t} 場戰鬥",
        "target_fn":         lambda lv: max(2,   1 + lv // 10),
        "reward_exp_fn":     lambda lv: lv * 22  + 55,
        "reward_credits_fn": lambda lv: lv * 28  + 110,
    },
    {
        "type": "buy_items",
        "icon": "🛒",
        "desc_fn":           lambda t:  f"購買 {t} 件道具",
        "target_fn":         lambda lv: max(2,   1 + lv // 10),
        "reward_exp_fn":     lambda lv: lv * 12  + 30,
        "reward_credits_fn": lambda lv: lv * 15  + 60,
    },
    {
        "type": "flee_success",
        "icon": "🏃",
        "desc_fn":           lambda t:  f"成功逃跑 {t} 次",
        "target_fn":         lambda lv: 2,
        "reward_exp_fn":     lambda lv: lv * 10  + 25,
        "reward_credits_fn": lambda lv: lv * 12  + 50,
    },
]


# ── Public helpers ───────────────────────────────────────────────

def generate_quests(level: int) -> list[dict]:
    """Pick 3 random quests scaled to player level."""
    chosen = random.sample(_TEMPLATES, 3)
    quests = []
    for t in chosen:
        target = t["target_fn"](level)
        quests.append({
            "type":            t["type"],
            "icon":            t["icon"],
            "desc":            t["desc_fn"](target),
            "target":          target,
            "progress":        0,
            "reward_exp":      t["reward_exp_fn"](level),
            "reward_credits":  t["reward_credits_fn"](level),
            "completed":       False,
            "claimed":         False,
        })
    return quests


def ensure_daily_quests(char: Character) -> list[dict]:
    """
    Return today's quests, regenerating if date changed.
    Mutates char.quests and sets flag_modified — must be inside a session.
    """
    today  = str(date.today())
    q_data = dict(char.quests or {})

    if q_data.get("date") != today:
        new_data = {"date": today, "quests": generate_quests(char.level)}
        char.quests = new_data
        flag_modified(char, "quests")
        return new_data["quests"]

    return q_data.get("quests", [])


def update_quest_progress(char: Character, quest_type: str, amount: int = 1) -> None:
    """
    Increment progress for the first uncompleted quest of quest_type.
    Synchronous — call inside an open session, then commit.
    """
    today  = str(date.today())
    q_data = dict(char.quests or {})
    if q_data.get("date") != today:
        return

    quests  = q_data.get("quests", [])
    changed = False
    for q in quests:
        if q["type"] == quest_type and not q["completed"]:
            q["progress"] = min(q["target"], q["progress"] + amount)
            if q["progress"] >= q["target"]:
                q["completed"] = True
            changed = True
            break

    if changed:
        char.quests = {"date": today, "quests": quests}
        flag_modified(char, "quests")


# ── Weekly quest templates ───────────────────────────────────────
# Harder targets, better rewards — resets every Monday

_WEEKLY_TEMPLATES: list[dict] = [
    {
        "type": "kill_enemies",
        "icon": "⚔️",
        "desc_fn":           lambda t:  f"本週擊殺 {t} 隻敵人",
        "target_fn":         lambda lv: max(20,  15 + lv),
        "reward_exp_fn":     lambda lv: lv * 100  + 300,
        "reward_credits_fn": lambda lv: lv * 120  + 500,
    },
    {
        "type": "earn_credits",
        "icon": "💰",
        "desc_fn":           lambda t:  f"本週賺取 {t:,} 信用點",
        "target_fn":         lambda lv: max(1000, lv * 400),
        "reward_exp_fn":     lambda lv: lv * 80   + 250,
        "reward_credits_fn": lambda lv: lv * 150  + 600,
    },
    {
        "type": "deal_damage",
        "icon": "💥",
        "desc_fn":           lambda t:  f"本週造成 {t:,} 點總傷害",
        "target_fn":         lambda lv: max(2000, lv * 300),
        "reward_exp_fn":     lambda lv: lv * 90   + 280,
        "reward_credits_fn": lambda lv: lv * 100  + 400,
    },
    {
        "type": "explore_times",
        "icon": "🔍",
        "desc_fn":           lambda t:  f"本週探索 {t} 次",
        "target_fn":         lambda lv: max(10,   8 + lv // 5),
        "reward_exp_fn":     lambda lv: lv * 70   + 200,
        "reward_credits_fn": lambda lv: lv * 90   + 350,
    },
    {
        "type": "use_skill",
        "icon": "💠",
        "desc_fn":           lambda t:  f"本週使用技能 {t} 次",
        "target_fn":         lambda lv: max(10,   8 + lv // 5),
        "reward_exp_fn":     lambda lv: lv * 80   + 220,
        "reward_credits_fn": lambda lv: lv * 95   + 380,
    },
    {
        "type": "loot_equipment",
        "icon": "📦",
        "desc_fn":           lambda t:  f"本週拾取 {t} 件裝備",
        "target_fn":         lambda lv: max(5,    4 + lv // 8),
        "reward_exp_fn":     lambda lv: lv * 110  + 350,
        "reward_credits_fn": lambda lv: lv * 130  + 520,
    },
]


def generate_weekly_quests(level: int) -> list[dict]:
    """Pick 3 random weekly quests scaled to player level."""
    chosen = random.sample(_WEEKLY_TEMPLATES, 3)
    quests = []
    for t in chosen:
        target = t["target_fn"](level)
        quests.append({
            "type":            t["type"],
            "icon":            t["icon"],
            "desc":            t["desc_fn"](target),
            "target":          target,
            "progress":        0,
            "reward_exp":      t["reward_exp_fn"](level),
            "reward_credits":  t["reward_credits_fn"](level),
            "completed":       False,
            "claimed":         False,
        })
    return quests


def ensure_weekly_quests(char: Character) -> list[dict]:
    """
    Return this week's quests, regenerating if week changed.
    Mutates char.weekly_quests — must be inside a session.
    """
    this_week = _iso_week(date.today())
    w_data    = dict(char.weekly_quests or {})

    if w_data.get("week") != this_week:
        new_data = {"week": this_week, "quests": generate_weekly_quests(char.level)}
        char.weekly_quests = new_data
        flag_modified(char, "weekly_quests")
        return new_data["quests"]

    return w_data.get("quests", [])


def update_weekly_quest_progress(char: Character, quest_type: str, amount: int = 1) -> None:
    """Increment weekly quest progress for quest_type. Call inside an open session."""
    this_week = _iso_week(date.today())
    w_data    = dict(char.weekly_quests or {})
    if w_data.get("week") != this_week:
        return

    quests  = w_data.get("quests", [])
    changed = False
    for q in quests:
        if q["type"] == quest_type and not q["completed"]:
            q["progress"] = min(q["target"], q["progress"] + amount)
            if q["progress"] >= q["target"]:
                q["completed"] = True
            changed = True
            break

    if changed:
        char.weekly_quests = {"week": this_week, "quests": quests}
        flag_modified(char, "weekly_quests")
