import random
from dataclasses import dataclass, field

from models.character import ClassType


def derive_player_stats(
    class_type: ClassType,
    vitality: int,
    reflex: int,
    tech: int,
    level: int,
) -> tuple[int, int]:
    """Returns (attack, defense). Primary stat varies by class."""
    primary = {
        ClassType.STREET_SAMURAI: vitality,
        ClassType.NETRUNNER:      tech,
        ClassType.SCAVENGER:      reflex,
    }[class_type]
    atk  = level * 3 + primary
    def_ = vitality + level          # full vitality counts toward defense
    return atk, def_


def roll_damage(attacker_atk: int, defender_def: int, crit_bonus: float = 0.0) -> tuple[int, bool]:
    """Returns (final_damage, is_critical).

    Defense is capped at 50% of attacker ATK so high-DEF chars still take
    meaningful damage and combat doesn't drag on forever.
    crit_bonus is added to the base 10% crit chance (e.g. 0.05 → 15% total).
    """
    effective_def = min(defender_def, attacker_atk // 2)
    base    = max(1, attacker_atk - effective_def)
    is_crit = random.random() < (0.10 + crit_bonus)
    jitter  = random.randint(-2, 2)
    dmg     = int(base * 1.5) + jitter if is_crit else base + jitter
    return max(1, dmg), is_crit


@dataclass
class CombatState:
    discord_user_id:        int
    character_id:           int
    char_name:              str
    char_class:             str
    char_level:             int
    hp:                     int
    hp_max:                 int
    energy:                 int
    energy_max:             int
    atk:                    int
    def_:                   int
    crit_bonus:             float            = 0.0   # extra crit chance from accessory
    enemy:                  dict             = field(default_factory=dict)
    enemy_hp:               int              = 0
    medkits:                int              = 0
    energy_cells_in_combat: int              = 0
    turn:                   int              = 0
    last_log:               list[str]        = field(default_factory=list)
    is_over:                bool             = False
    player_won:             bool             = False
    # ── Status effects ────────────────────────────────────────────
    # Each entry: {"type": str, "turns_left": int, "value": float}
    # Types on enemy: "poison", "burn", "shock" (can't act), "stun" (can't act)
    # Types on player: "atk_buff" (mult), "dodge_next" (bool)
    player_statuses:        list[dict]       = field(default_factory=list)
    enemy_statuses:         list[dict]       = field(default_factory=list)
    # ── Combo ─────────────────────────────────────────────────────
    combo:                  int              = 0
    # ── Backward-compat shim (enemy stunned for 1 turn) ──────────
    enemy_stunned:          bool             = False
    # ── Quest tracking (batched at end of fight) ──────────────────
    damage_dealt:           int              = 0
    crits_landed:           int              = 0
    skills_used:            int              = 0
    items_used_in_fight:    int              = 0


# ── Status effect helpers ────────────────────────────────────────

def add_status(statuses: list[dict], effect_type: str, turns: int, value: float = 0.0) -> None:
    """Add or refresh a status effect."""
    for s in statuses:
        if s["type"] == effect_type:
            s["turns_left"] = max(s["turns_left"], turns)
            return
    statuses.append({"type": effect_type, "turns_left": turns, "value": value})


def has_status(statuses: list[dict], effect_type: str) -> bool:
    return any(s["type"] == effect_type for s in statuses)


def tick_statuses(statuses: list[dict], hp: int, hp_max: int) -> tuple[int, list[str]]:
    """Process status effects at the start of a turn. Returns (hp_after, log_lines)."""
    logs: list[str] = []
    expired: list[dict] = []

    for s in statuses:
        if s["type"] in ("poison", "burn"):
            dmg = max(1, int(hp_max * s["value"]))
            hp  = max(0, hp - dmg)
            emoji = "🦠" if s["type"] == "poison" else "🔥"
            logs.append(f"{emoji} **{s['type'].capitalize()}** 造成 **{dmg}** 點傷害！（剩餘 {s['turns_left']-1} 回）")
        elif s["type"] == "shock":
            dmg = max(1, int(hp_max * s["value"]))
            hp  = max(0, hp - dmg)
            logs.append(f"⚡ **感電** 造成 **{dmg}** 點傷害！（剩餘 {s['turns_left']-1} 回）")
        s["turns_left"] -= 1
        if s["turns_left"] <= 0:
            expired.append(s)

    for s in expired:
        statuses.remove(s)

    return hp, logs


def is_immobilised(statuses: list[dict]) -> bool:
    """Returns True if the entity cannot act this turn (stun/shock count as immobilise)."""
    return has_status(statuses, "stun") or has_status(statuses, "stun_hack")


def fmt_statuses(statuses: list[dict]) -> str:
    """Format status list for display, e.g. '🦠×3  ⚡×2'."""
    _ICONS = {"poison": "🦠", "burn": "🔥", "shock": "⚡", "stun": "💫", "stun_hack": "💫", "atk_buff": "💪", "dodge_next": "💨"}
    parts = [f"{_ICONS.get(s['type'], '?')}×{s['turns_left']}" for s in statuses]
    return "  ".join(parts) if parts else ""
