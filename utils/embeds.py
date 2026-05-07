from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from config import CLASS_BASE_STATS, CLASS_DISPLAY, COMBO_MAX, STAT_POINTS_PER_LEVEL, exp_for_next_level
from utils.bars import energy_bar, exp_bar, hp_bar, make_bar

if TYPE_CHECKING:
    from models.character import Character
    from services.combat_service import CombatState

# ── Cyberpunk colour palette ────────────────────────────────────
C_PRIMARY = 0x00FF41   # matrix green  — success / default
C_DANGER  = 0xFF0041   # neon red      — errors / low HP
C_WARNING = 0xFFAA00   # amber         — mid HP
C_INFO    = 0x00D4FF   # electric blue — informational
C_MYTHIC  = 0xBF00FF   # neon purple   — mythic rarity
C_DARK    = 0x0A0E1A   # dark navy     — neutral UI


# ── Helpers ─────────────────────────────────────────────────────

def _hp_colour(current: int, maximum: int) -> int:
    ratio = current / maximum if maximum else 0
    if ratio > 0.6:
        return C_PRIMARY
    if ratio > 0.3:
        return C_WARNING
    return C_DANGER


# ── Generic embeds ───────────────────────────────────────────────

def error_embed(description: str) -> discord.Embed:
    return discord.Embed(description=f"⛔  {description}", color=C_DANGER)


def success_embed(description: str) -> discord.Embed:
    return discord.Embed(description=f"✅  {description}", color=C_PRIMARY)


# ── Game-specific embeds ─────────────────────────────────────────

def class_select_embed() -> discord.Embed:
    s = CLASS_BASE_STATS
    d = CLASS_DISPLAY

    lines: list[str] = [
        "在廢土中，你的職業決定了你的生存方式。",
        "**選擇一條路——沒有回頭的機會。**\n",
    ]
    for key in ("street_samurai", "netrunner", "scavenger"):
        info  = d[key]
        stats = s[key]
        lines.append(
            f"{info['emoji']}  **{info['name']}**\n"
            f"> {info['desc']}\n"
            f"> `HP {stats['hp']}` · `⚡ {stats['energy']}`  "
            f"│  體 **{stats['vitality']}** / 反 **{stats['reflex']}** / 科 **{stats['tech']}**"
        )

    embed = discord.Embed(
        title="▸ 廢土識別系統  —  職業選擇",
        description="\n\n".join(lines),
        color=C_DARK,
    )
    embed.set_footer(text="從下方選單選擇你的職業路徑  ·  選擇後將跳出命名視窗")
    return embed


def character_profile_embed(character: Character) -> discord.Embed:
    from services.combat_service import derive_player_stats
    from services.equipment_service import equipped_bonuses, get_item
    from services.title_service import equipped_title_data, rarity_emoji, title_bonuses

    class_info = CLASS_DISPLAY[character.class_type.value]
    exp_needed = exp_for_next_level(character.level)

    atk_b, def_b, hp_b, energy_b, crit_b = equipped_bonuses(
        character.equipped_weapon, character.equipped_armor,
        character.item_enhancements,
        character.equipped_helmet, character.equipped_accessory,
        character.custom_items,
    )
    base_atk, base_def = derive_player_stats(
        character.class_type, character.stat_vitality,
        character.stat_reflex, character.stat_tech, character.level,
    )
    # Apply title bonuses to displayed combat values
    tb = title_bonuses(character)
    atk  = int((base_atk + atk_b) * (1.0 + tb.get("atk_pct", 0.0)))
    def_ = int((base_def + def_b) * (1.0 + tb.get("def_pct", 0.0)))

    title      = equipped_title_data(character)
    title_line = f"{rarity_emoji(title['rarity'])} {title['emoji']} **{title['name']}**\n"

    description = title_line + "\n".join([
        hp_bar(character.hp_current, character.hp_max),
        energy_bar(character.energy_current, character.energy_max),
        exp_bar(character.exp, exp_needed),
    ])

    embed = discord.Embed(
        title=f"{class_info['emoji']}  {character.name}",
        description=description,
        color=_hp_colour(character.hp_current, character.hp_max),
    )

    # Row 1 — identity
    embed.add_field(name="職業",    value=class_info["name"],               inline=True)
    embed.add_field(name="等級",    value=f"Lv.{character.level}",          inline=True)
    embed.add_field(name="✨ 轉生", value=f"{character.rebirth_count} 次",  inline=True)

    # Row 2 — base stats
    embed.add_field(name="💪 體力",     value=str(character.stat_vitality), inline=True)
    embed.add_field(name="⚡ 反應神經", value=str(character.stat_reflex),   inline=True)
    embed.add_field(name="🔧 科技力",   value=str(character.stat_tech),     inline=True)

    # Row 3 — combat power (include title crit bonus)
    crit_pct = int((crit_b + tb.get("crit_bonus", 0.0)) * 100)
    embed.add_field(name="⚔️ ATK",       value=str(atk),                          inline=True)
    embed.add_field(name="🛡️ DEF",       value=str(def_),                         inline=True)
    embed.add_field(name="💥 暴擊率",    value=f"{10 + crit_pct}%",               inline=True)

    # Row 4 — economy & stats
    embed.add_field(name="💰 信用點",   value=f"{character.credits:,}",      inline=True)
    embed.add_field(name="⚔️ 擊殺數",   value=f"{character.kills:,}",        inline=True)
    embed.add_field(name="✨ 可用點數", value=str(character.stat_points_avail), inline=True)

    # Row 5 — equipment (weapon/armor) — pass custom_items so shop gear resolves
    ci = character.custom_items or {}
    w   = get_item(character.equipped_weapon, ci)    if character.equipped_weapon    else None
    a   = get_item(character.equipped_armor, ci)     if character.equipped_armor     else None
    h   = get_item(character.equipped_helmet, ci)    if character.equipped_helmet    else None
    acc = get_item(character.equipped_accessory, ci) if character.equipped_accessory else None
    w_txt   = f"{w['emoji']} {w['name']} `+{w.get('atk_bonus', 0)} ATK`" if w else "`空`"
    a_txt   = f"{a['emoji']} {a['name']} `+{a.get('def_bonus', 0)} DEF`" if a else "`空`"
    h_txt   = f"{h['emoji']} {h['name']} `+{h.get('def_bonus', 0)} DEF`" if h else "`空`"
    acc_txt = f"{acc['emoji']} {acc['name']}" if acc else "`空`"

    embed.add_field(name="⚔️ 武器",  value=w_txt,   inline=True)
    embed.add_field(name="🛡️ 護甲",  value=a_txt,   inline=True)
    embed.add_field(name="⛑️ 頭盔",  value=h_txt,   inline=True)
    embed.add_field(name="💠 配件",  value=acc_txt, inline=True)
    embed.add_field(name="🎒 背包",  value=f"{len(character.inventory or [])} / 20", inline=True)
    embed.add_field(name="🩹 急救包", value=str(character.medkits), inline=True)

    embed.set_footer(text=f"📍 {character.current_location}")
    return embed


def allocate_embed(character) -> discord.Embed:
    from services.combat_service import derive_player_stats

    atk, def_ = derive_player_stats(
        character.class_type, character.stat_vitality,
        character.stat_reflex, character.stat_tech, character.level,
    )
    pts   = character.stat_points_avail
    color = C_INFO if pts > 0 else C_DARK

    desc = (
        f"✨  **可用點數：{pts}**\n\n"
        f"💪  體力　　　`{character.stat_vitality}`　→  HP 上限 **+8 / 點**，強化防禦\n"
        f"⚡  反應神經　`{character.stat_reflex}`　→  拾荒者主攻擊力來源\n"
        f"🔧  科技力　　`{character.stat_tech}`　→  竄網使主攻擊力來源\n\n"
        f"─────────────────────────\n"
        f"⚔️ ATK **{atk}**  │  🛡️ DEF **{def_}**  │  "
        f"❤️ `{character.hp_current} / {character.hp_max}`"
    )
    embed = discord.Embed(
        title=f"⚙️  屬性配點  —  {character.name}  Lv.{character.level}",
        description=desc,
        color=color,
    )
    embed.set_footer(
        text="所有點數已分配完畢" if pts == 0 else f"點擊按鈕配點  ·  剩餘 {pts} 點"
    )
    return embed


# ── Combat embeds ────────────────────────────────────────────────

def combat_embed(state: CombatState) -> discord.Embed:
    from config import CLASS_SKILLS, COMBO_BONUS
    from services.combat_service import fmt_statuses

    enemy = state.enemy
    enemy_bar = (
        f"❤️  `{make_bar(state.enemy_hp, enemy['hp'])}`  "
        f"**{state.enemy_hp}** / {enemy['hp']}"
    )

    # Build skill hint: show all 3 skills briefly
    skills    = CLASS_SKILLS[state.char_class]
    skill_str = "  ".join(
        f"{s['emoji']}{s['name']}({s['energy_cost']})" for s in skills
    )

    # Combo display
    combo_txt = ""
    if state.combo > 0:
        combo_bar = "🔥" * state.combo + "·" * (COMBO_MAX - state.combo)
        bonus_pct = int(state.combo * COMBO_BONUS * 100)
        combo_txt = f"\n🔥 **連擊 ×{state.combo}**  `{combo_bar}`  ATK +**{bonus_pct}%**"

    # Status effects on player
    p_status = fmt_statuses(state.player_statuses)
    p_status_txt = f"\n✦ 你的狀態：{p_status}" if p_status else ""

    # Status effects on enemy
    e_status = fmt_statuses(state.enemy_statuses)
    e_status_txt = f"\n✦ 敵方狀態：{e_status}" if e_status else ""

    lines = [
        f"**{state.char_name}**",
        hp_bar(state.hp, state.hp_max),
        energy_bar(state.energy, state.energy_max),
        f"🩹 ×{state.medkits}　🔋 ×{state.energy_cells_in_combat}"
        f"　│　💠 {skill_str}",
        combo_txt + p_status_txt,
        "",
        f"{enemy['emoji']}  **{enemy['name']}**  Lv.{enemy['level']}",
        enemy_bar + e_status_txt,
        "",
        "─────────────────────────",
    ]
    for entry in (state.last_log[-3:] or ["⚡ 戰鬥開始！選擇你的行動。"]):
        lines.append(f"> {entry}")

    ratio = state.hp / state.hp_max if state.hp_max else 0
    color = C_DANGER if ratio < 0.3 else C_WARNING if ratio < 0.6 else C_PRIMARY

    embed = discord.Embed(
        title=f"⚔️  戰鬥  │  第 {state.turn} 回合",
        description="\n".join(lines),
        color=color,
    )
    embed.set_footer(text=f"ATK {state.atk}  │  DEF {state.def_}  │  暴擊率 {int((0.10+state.crit_bonus)*100)}%")
    return embed


def end_combat_embed(
    state: CombatState,
    outcome: str,
    exp_gain: int = 0,
    credits_gain: int = 0,
    leveled_up: bool = False,
    new_level: int = 0,
    drop: dict | None = None,
    mat_drop: dict | None = None,
    new_achievements: list[str] | None = None,
) -> discord.Embed:
    enemy = state.enemy

    if outcome == "win":
        title = f"✅  勝利！擊敗了 {enemy['emoji']} {enemy['name']}"
        color = C_PRIMARY
        desc  = (
            f"獲得 **{exp_gain}** EXP  │  **{credits_gain}** 💰\n"
            f"剩餘 HP：**{state.hp}** / {state.hp_max}"
        )
        if leveled_up:
            desc += (
                f"\n\n🎉  **升級！Lv.{new_level}**  "
                f"獲得 **{STAT_POINTS_PER_LEVEL}** 屬性點，使用 `/allocate` 分配。"
            )
    elif outcome == "lose":
        title = f"💀  戰鬥失敗  —  被 {enemy['emoji']} {enemy['name']} 擊倒"
        color = C_DANGER
        desc  = "你失去意識，在最近的安全區醒來。\nHP 已恢復至 **25%**，使用 `/rest` 完全恢復。"
    else:  # flee
        title = "🏃  成功逃脫"
        color = C_WARNING
        desc  = f"你脫離了 {enemy['emoji']} **{enemy['name']}** 的攻擊範圍。"

    embed = discord.Embed(title=title, description=desc, color=color)

    if drop:
        if "atk_bonus" in drop:
            bonus = f"+{drop['atk_bonus']} ATK"
        elif "def_bonus" in drop:
            bonus = f"+{drop['def_bonus']} DEF"
        else:
            bonus = ""
        embed.add_field(
            name="📦 裝備掉落",
            value=f"{drop['emoji']} **{drop['name']}** `{bonus}` 已加入背包",
            inline=False,
        )

    if mat_drop:
        embed.add_field(
            name="🧪 材料掉落",
            value=f"{mat_drop['emoji']} **{mat_drop['name']}** 已加入材料欄",
            inline=False,
        )

    if new_achievements:
        embed.add_field(
            name="🏆 解鎖成就",
            value="  ".join(new_achievements),
            inline=False,
        )

    embed.set_footer(text=f"共 {state.turn} 回合")
    return embed
