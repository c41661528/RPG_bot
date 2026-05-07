"""
PvP duel system — auto-resolved combat between two real players.
Combat applies real stats including equipment, enhancements, and title bonuses.
"""
from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy.orm.attributes import flag_modified

from services.combat_service import derive_player_stats, roll_damage
from services.equipment_service import equipped_bonuses
from services.title_service import title_bonuses

if TYPE_CHECKING:
    from models.character import Character


DUEL_COOLDOWN_SEC = 30 * 60        # 30 minutes between duels
DUEL_DAILY_LIMIT  = 5              # max duels per day
DUEL_TURN_CAP     = 60             # safety net for runaway fights


# ── Date helpers ──────────────────────────────────────────────────

def today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Eligibility ──────────────────────────────────────────────────

def can_duel(char: Character) -> tuple[bool, str]:
    if char.is_in_combat:
        return False, "戰鬥中無法決鬥。"

    stats = char.pvp_stats or {}
    today = today_iso()
    if stats.get("duels_date") == today and stats.get("duels_today", 0) >= DUEL_DAILY_LIMIT:
        return False, f"今日決鬥次數已達上限（{DUEL_DAILY_LIMIT}）。"

    last = stats.get("last_duel_at")
    if last:
        try:
            last_dt = datetime.fromisoformat(last)
            elapsed = (datetime.now(timezone.utc) - last_dt).total_seconds()
            if elapsed < DUEL_COOLDOWN_SEC:
                remaining = int(DUEL_COOLDOWN_SEC - elapsed)
                return False, f"決鬥冷卻中（剩 {remaining // 60} 分 {remaining % 60} 秒）。"
        except ValueError:
            pass
    return True, ""


# ── Combat snapshot ──────────────────────────────────────────────

def player_combat_stats(char: Character) -> dict:
    """Snapshot a fighter's PvP stats with equipment + title bonuses applied."""
    atk_b, def_b, hp_b, _energy_b, crit_b = equipped_bonuses(
        char.equipped_weapon, char.equipped_armor,
        char.item_enhancements,
        char.equipped_helmet, char.equipped_accessory,
        char.custom_items,
    )
    base_atk, base_def = derive_player_stats(
        char.class_type, char.stat_vitality,
        char.stat_reflex, char.stat_tech, char.level,
    )
    tb = title_bonuses(char)

    atk    = int((base_atk + atk_b) * (1.0 + tb.get("atk_pct", 0.0)))
    def_   = int((base_def + def_b) * (1.0 + tb.get("def_pct", 0.0)))
    hp_max = int((char.hp_max + hp_b) * (1.0 + tb.get("hp_pct", 0.0)))
    crit   = crit_b + tb.get("crit_bonus", 0.0)

    return {
        "char_id":   char.id,
        "name":      char.name,
        "level":     char.level,
        "hp":        hp_max,
        "hp_max":    hp_max,
        "atk":       atk,
        "def_":      def_,
        "crit_bonus": crit,
    }


# ── Simulation ───────────────────────────────────────────────────

def simulate_duel(p1: dict, p2: dict) -> tuple[dict, dict, list[str]]:
    """
    Run an auto-fight between two stat snapshots.
    Returns (winner_dict, loser_dict, log_lines).

    Snapshots are mutated in place — pass copies if you need to keep originals.
    """
    logs: list[str] = []
    turn = 0
    a, b = (p1, p2) if random.random() < 0.5 else (p2, p1)

    while a["hp"] > 0 and b["hp"] > 0 and turn < DUEL_TURN_CAP:
        turn += 1
        # a → b
        dmg, crit = roll_damage(a["atk"], b["def_"], a.get("crit_bonus", 0.0))
        b["hp"] = max(0, b["hp"] - dmg)
        crit_t = " 💥" if crit else ""
        logs.append(
            f"R{turn}: {a['name']} → {b['name']}　**{dmg}**{crit_t}　"
            f"({b['hp']}/{b['hp_max']})"
        )
        if b["hp"] <= 0:
            break

        # b → a
        dmg, crit = roll_damage(b["atk"], a["def_"], b.get("crit_bonus", 0.0))
        a["hp"] = max(0, a["hp"] - dmg)
        crit_t = " 💥" if crit else ""
        logs.append(
            f"R{turn}: {b['name']} → {a['name']}　**{dmg}**{crit_t}　"
            f"({a['hp']}/{a['hp_max']})"
        )

    if a["hp"] <= 0 and b["hp"] > 0:
        winner, loser = b, a
    elif b["hp"] <= 0 and a["hp"] > 0:
        winner, loser = a, b
    else:
        # Cap reached or both at 0 — pick whoever has more remaining HP%
        a_pct = a["hp"] / a["hp_max"] if a["hp_max"] else 0
        b_pct = b["hp"] / b["hp_max"] if b["hp_max"] else 0
        winner, loser = (a, b) if a_pct >= b_pct else (b, a)
        logs.append(f"⏱ 達 {DUEL_TURN_CAP} 回合上限，依剩餘 HP 判勝。")

    return winner, loser, logs


# ── Rewards & bookkeeping ────────────────────────────────────────

def calc_rewards(winner_lv: int, loser_lv: int, loser_credits: int) -> tuple[int, int]:
    """Returns (credits_gain, exp_gain)."""
    credits_gain = min(1000, max(50, int(loser_credits * 0.05)))
    exp_gain     = int(loser_lv * 25 + max(0, loser_lv - winner_lv) * 15)
    return credits_gain, exp_gain


def record_duel(char: Character, won: bool) -> None:
    """Update PvP stats / cooldown. Call inside an open session."""
    stats = dict(char.pvp_stats or {})
    today = today_iso()
    if stats.get("duels_date") != today:
        stats["duels_today"] = 0
        stats["duels_date"]  = today
    stats["duels_today"]  = stats.get("duels_today", 0) + 1
    stats["last_duel_at"] = now_iso()
    if won:
        stats["wins"] = stats.get("wins", 0) + 1
    else:
        stats["losses"] = stats.get("losses", 0) + 1
    char.pvp_stats = stats
    flag_modified(char, "pvp_stats")


def duels_today(char: Character) -> int:
    stats = char.pvp_stats or {}
    return stats.get("duels_today", 0) if stats.get("duels_date") == today_iso() else 0
