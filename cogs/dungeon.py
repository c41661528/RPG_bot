"""
Dungeon system — 5-floor progressive challenge with auto-resolved combat.
Each floor is computed instantly; the player decides to advance or retreat
between floors via buttons.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

import discord
from discord.ext import commands
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from config import MAX_LEVEL, STAT_POINTS_PER_LEVEL, exp_for_next_level
from database.session import AsyncSessionFactory
from models.character import Character
from models.player import Player
from services.achievement_service import check_achievements, unlock_achievement
from services.combat_service import derive_player_stats, roll_damage
from services.equipment_service import equipped_bonuses, try_drop_material
from services.quest_service import update_quest_progress, update_weekly_quest_progress
from utils.embeds import C_DANGER, C_INFO, C_PRIMARY, C_WARNING, error_embed, success_embed

_DUNGEONS_PATH = Path(__file__).parent.parent / "data" / "dungeons.json"


def _load_dungeons() -> list[dict]:
    with open(_DUNGEONS_PATH, encoding="utf-8") as f:
        return json.load(f)


_DUNGEONS: list[dict] = _load_dungeons()
_DUNGEON_MAP: dict[str, dict] = {d["id"]: d for d in _DUNGEONS}


# ── Auto-combat helper ───────────────────────────────────────────

def _auto_fight_floor(
    player_hp: int, player_hp_max: int,
    player_atk: int, player_def: int,
    enemy: dict,
) -> tuple[int, bool, int, list[str]]:
    """
    Simulate a floor fight without user input.
    Returns (hp_remaining, player_won, turns, log_lines).
    """
    e_hp  = enemy["hp"]
    logs: list[str] = []
    turn  = 0

    while player_hp > 0 and e_hp > 0 and turn < 50:
        turn += 1
        # Player attacks
        p_dmg, p_crit = roll_damage(player_atk, enemy["defense"])
        e_hp = max(0, e_hp - p_dmg)
        crit_txt = " 💥" if p_crit else ""
        logs.append(f"你 **{p_dmg}**{crit_txt}  →  {enemy['emoji']} {e_hp} HP")
        if e_hp <= 0:
            break

        # Enemy attacks
        e_dmg, e_crit = roll_damage(enemy["attack"], player_def)
        player_hp = max(0, player_hp - e_dmg)
        e_crit_txt = " 💥" if e_crit else ""
        logs.append(f"{enemy['emoji']} **{e_dmg}**{e_crit_txt}  →  你 {player_hp} HP")

    return player_hp, e_hp <= 0, turn, logs[-6:]   # keep last 6 lines


def _build_floor_enemy(dungeon: dict, floor_idx: int, player_level: int) -> dict:
    """Scale a dungeon floor enemy from the template."""
    tmpl = dungeon["floor_enemies"][floor_idx]
    base_hp  = max(20, player_level * 15)
    base_atk = max(5,  player_level * 3)
    base_def = max(2,  player_level)

    return {
        "name":    tmpl["name"],
        "emoji":   tmpl["emoji"],
        "level":   player_level,
        "hp":      int(base_hp  * tmpl["hp_mult"]),
        "attack":  int(base_atk * tmpl["atk_mult"]),
        "defense": int(base_def * tmpl["def_mult"]),
        "exp_mult":     tmpl["exp_mult"],
        "credits_mult": tmpl["credits_mult"],
    }


# ── Embeds ───────────────────────────────────────────────────────

def _select_embed() -> discord.Embed:
    lines: list[str] = []
    for d in _DUNGEONS:
        lines.append(
            f"{d['emoji']} **{d['name']}**  `需 Lv.{d['min_level']}`\n"
            f"> {d['desc']}"
        )
    embed = discord.Embed(
        title="🗺️  迷宮挑戰",
        description="\n\n".join(lines),
        color=C_INFO,
    )
    embed.set_footer(text="選擇下方迷宮進入  ·  全 5 層  ·  Boss 在第 5 層")
    return embed


def _floor_result_embed(
    dungeon: dict, floor: int, enemy: dict,
    hp_before: int, hp_after: int, hp_max: int,
    won: bool, turns: int, combat_log: list[str],
    exp_gain: int, credits_gain: int,
) -> discord.Embed:
    is_boss = floor == 5
    title_emoji = "👹" if is_boss else f"**{floor}**"

    if won:
        title = f"✅  第 {floor} 層 {'【BOSS】 ' if is_boss else ''}通過！"
        color = C_PRIMARY
    else:
        title = f"💀  第 {floor} 層  —  被 {enemy['emoji']} **{enemy['name']}** 擊倒"
        color = C_DANGER

    hp_bar = f"❤️ `{hp_before}` → `{hp_after}` / {hp_max}"
    desc_lines = [
        f"對手：{enemy['emoji']} **{enemy['name']}**",
        hp_bar,
        f"回合數：{turns}",
        "",
        "────────────────",
    ] + [f"> {l}" for l in combat_log]

    if won:
        desc_lines += ["", f"🎖️ +**{exp_gain}** EXP  │  💰 +**{credits_gain:,}**"]

    embed = discord.Embed(title=title, description="\n".join(desc_lines), color=color)
    return embed


def _dungeon_clear_embed(
    dungeon: dict, char_name: str,
    total_exp: int, total_credits: int, leveled_up: bool, new_level: int,
    new_ach: list[str],
) -> discord.Embed:
    embed = discord.Embed(
        title=f"🏆  迷宮通關！{dungeon['emoji']} **{dungeon['name']}**",
        description=(
            f"恭喜 **{char_name}** 通關全 5 層迷宮！\n\n"
            f"🎖️ 總計獲得：**{total_exp}** EXP  │  💰 **{total_credits:,}** 信用點\n"
            f"🎁 通關獎勵：**{dungeon['clear_bonus_exp']}** EXP  │  "
            f"💰 **{dungeon['clear_bonus_credits']:,}**"
        ),
        color=C_PRIMARY,
    )
    if leveled_up:
        embed.add_field(
            name="🎉 升級！",
            value=f"等級提升至 **Lv.{new_level}**！使用 `/allocate` 分配屬性點。",
            inline=False,
        )
    if new_ach:
        embed.add_field(
            name="🏆 解鎖成就",
            value="、".join(new_ach),
            inline=False,
        )
    return embed


# ── Views ────────────────────────────────────────────────────────

class _DungeonSelect(discord.ui.Select):
    def __init__(self, char: Character, cog: DungeonCog) -> None:
        self.cog     = cog
        self.char_id = char.id

        options: list[discord.SelectOption] = []
        for d in _DUNGEONS:
            locked = char.level < d["min_level"]
            options.append(
                discord.SelectOption(
                    label=f"{d['name']}  Lv.{d['min_level']}+",
                    value=d["id"],
                    emoji=d["emoji"],
                    description="🔒 等級不足" if locked else d["desc"][:40],
                )
            )

        super().__init__(
            placeholder="選擇迷宮...",
            options=options,
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        parent: DungeonSelectView = self.view  # type: ignore[assignment]
        if interaction.user.id != parent.discord_user_id:
            return await interaction.response.send_message("這不是你的面板！", ephemeral=True)
        await self.cog.start_dungeon(interaction, self.char_id, self.values[0])


class DungeonSelectView(discord.ui.View):
    def __init__(self, char: Character, cog: DungeonCog) -> None:
        super().__init__(timeout=60)
        self.discord_user_id = char.player_id  # overridden by cog
        self.add_item(_DungeonSelect(char, cog))


class FloorView(discord.ui.View):
    def __init__(
        self, cog: DungeonCog, char_id: int, discord_user_id: int,
        dungeon_id: str, floor: int, hp: int, hp_max: int,
        energy: int, atk: int, def_: int,
        total_exp: int, total_credits: int,
    ) -> None:
        super().__init__(timeout=120)
        self.cog             = cog
        self.char_id         = char_id
        self.discord_user_id = discord_user_id
        self.dungeon_id      = dungeon_id
        self.floor           = floor
        self.hp              = hp
        self.hp_max          = hp_max
        self.energy          = energy
        self.atk             = atk
        self.def_            = def_
        self.total_exp       = total_exp
        self.total_credits   = total_credits

        if floor >= 5:
            # All floors done — only "end" button
            self.children[0].disabled = True
            self.children[1].label    = "完成迷宮"

    @discord.ui.button(label="繼續下一層 ▸", emoji="⚔️", style=discord.ButtonStyle.danger, row=0)
    async def next_floor(
        self, button: discord.ui.Button, interaction: discord.Interaction
    ) -> None:
        if interaction.user.id != self.discord_user_id:
            return await interaction.response.send_message("這不是你的戰鬥！", ephemeral=True)
        await self.cog.advance_floor(
            interaction, self.char_id, self.dungeon_id,
            self.floor + 1, self.hp, self.hp_max, self.energy,
            self.atk, self.def_, self.total_exp, self.total_credits,
        )

    @discord.ui.button(label="撤退（保留已得獎勵）", emoji="🏃", style=discord.ButtonStyle.secondary, row=0)
    async def retreat(
        self, button: discord.ui.Button, interaction: discord.Interaction
    ) -> None:
        if interaction.user.id != self.discord_user_id:
            return await interaction.response.send_message("這不是你的戰鬥！", ephemeral=True)
        await self.cog.finish_dungeon(
            interaction, self.char_id,
            self.total_exp, self.total_credits,
            fled=True,
        )


# ── Cog ──────────────────────────────────────────────────────────

class DungeonCog(commands.Cog):
    def __init__(self, bot: discord.Bot) -> None:
        self.bot = bot

    @discord.slash_command(name="dungeon", description="🗺️ 挑戰迷宮（5層+Boss）")
    async def dungeon(self, ctx: discord.ApplicationContext) -> None:
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                select(Character)
                .join(Player, Character.player_id == Player.id)
                .where(Player.discord_id == ctx.author.id)
            )
            char = result.scalar_one_or_none()

        if char is None:
            return await ctx.respond(embed=error_embed("尚未建立角色。使用 `/start`。"), ephemeral=True)
        if char.is_in_combat:
            return await ctx.respond(embed=error_embed("先結束當前戰鬥！"), ephemeral=True)
        if char.hp_current <= char.hp_max // 4:
            return await ctx.respond(
                embed=error_embed("HP 過低，無法進入迷宮。使用 `/rest` 恢復體力。"),
                ephemeral=True,
            )

        view = DungeonSelectView(char, self)
        view.discord_user_id = ctx.author.id
        await ctx.respond(embed=_select_embed(), view=view, ephemeral=True)

    async def start_dungeon(
        self,
        interaction: discord.Interaction,
        char_id: int,
        dungeon_id: str,
    ) -> None:
        dungeon = _DUNGEON_MAP.get(dungeon_id)
        if not dungeon:
            return await interaction.response.send_message("迷宮不存在。", ephemeral=True)

        async with AsyncSessionFactory() as session:
            result = await session.execute(select(Character).where(Character.id == char_id))
            char   = result.scalar_one()

            if char.level < dungeon["min_level"]:
                return await interaction.response.send_message(
                    f"需要 Lv.{dungeon['min_level']} 才能進入此迷宮。", ephemeral=True
                )

            atk_b, def_b, hp_b, energy_b, crit_b = equipped_bonuses(
                char.equipped_weapon, char.equipped_armor,
                char.item_enhancements,
                char.equipped_helmet, char.equipped_accessory,
            )
            base_atk, base_def = derive_player_stats(
                char.class_type, char.stat_vitality,
                char.stat_reflex, char.stat_tech, char.level,
            )
            player_atk = base_atk + atk_b
            player_def = base_def + def_b
            player_hp  = char.hp_current
            player_hp_max = char.hp_max
            player_energy = char.energy_current
            discord_uid   = interaction.user.id

        await self.advance_floor(
            interaction, char_id, dungeon_id,
            floor=1,
            hp=player_hp, hp_max=player_hp_max,
            energy=player_energy,
            atk=player_atk, def_=player_def,
            total_exp=0, total_credits=0,
        )

    async def advance_floor(
        self,
        interaction: discord.Interaction,
        char_id: int,
        dungeon_id: str,
        floor: int,
        hp: int, hp_max: int,
        energy: int,
        atk: int, def_: int,
        total_exp: int, total_credits: int,
    ) -> None:
        dungeon = _DUNGEON_MAP[dungeon_id]
        floor_idx = floor - 1

        async with AsyncSessionFactory() as session:
            result = await session.execute(select(Character).where(Character.id == char_id))
            char   = result.scalar_one()
            level  = char.level
            discord_uid = interaction.user.id

        enemy = _build_floor_enemy(dungeon, floor_idx, level)

        # Auto-resolve the fight
        exp_per_floor     = int(enemy["hp"] // 2 * enemy["exp_mult"])
        credits_per_floor = int(random.randint(level * 10, level * 25) * enemy["credits_mult"])

        hp_after, won, turns, combat_log = _auto_fight_floor(
            hp, hp_max, atk, def_, enemy
        )

        if not won:
            # Player lost this floor — end dungeon, give partial rewards
            embed = _floor_result_embed(
                dungeon, floor, enemy,
                hp, hp_after, hp_max,
                False, turns, combat_log,
                0, 0,
            )
            await interaction.response.edit_message(embed=embed, view=None)
            await self.finish_dungeon(
                interaction, char_id,
                total_exp, total_credits,
                fled=False, followup=True,
            )
            return

        total_exp     += exp_per_floor
        total_credits += credits_per_floor

        embed = _floor_result_embed(
            dungeon, floor, enemy,
            hp, hp_after, hp_max,
            True, turns, combat_log,
            exp_per_floor, credits_per_floor,
        )

        if floor >= 5:
            # All floors cleared!
            await interaction.response.edit_message(embed=embed, view=None)
            await self.finish_dungeon(
                interaction, char_id,
                total_exp, total_credits,
                dungeon_id=dungeon_id,
                fled=False, followup=True,
            )
        else:
            view = FloorView(
                self, char_id, interaction.user.id,
                dungeon_id, floor, hp_after, hp_max,
                energy, atk, def_,
                total_exp, total_credits,
            )
            await interaction.response.edit_message(embed=embed, view=view)

    async def finish_dungeon(
        self,
        interaction: discord.Interaction,
        char_id: int,
        exp_gain: int,
        credits_gain: int,
        dungeon_id: str = "",
        fled: bool = False,
        followup: bool = False,
    ) -> None:
        dungeon = _DUNGEON_MAP.get(dungeon_id)
        cleared = bool(dungeon and not fled)

        bonus_exp  = dungeon["clear_bonus_exp"]     if cleared else 0
        bonus_cred = dungeon["clear_bonus_credits"]  if cleared else 0
        exp_gain     += bonus_exp
        credits_gain += bonus_cred

        leveled_up  = False
        new_level   = 1
        new_ach: list[str] = []
        char_name   = "？"

        async with AsyncSessionFactory() as session:
            result = await session.execute(select(Character).where(Character.id == char_id))
            char   = result.scalar_one()
            char_name  = char.name
            new_level  = char.level

            char.exp     += exp_gain
            char.credits += credits_gain
            char.hp_current = max(1, char.hp_current - (char.hp_max // 2) if not cleared else char.hp_current)

            # Quest progress
            update_quest_progress(char, "kill_enemies", 5 if cleared else 2)
            update_weekly_quest_progress(char, "kill_enemies", 5 if cleared else 2)
            update_quest_progress(char, "earn_credits", credits_gain)
            update_weekly_quest_progress(char, "earn_credits", credits_gain)

            # Level up
            while char.exp >= exp_for_next_level(char.level) and char.level < MAX_LEVEL:
                char.exp -= exp_for_next_level(char.level)
                char.level += 1
                char.stat_points_avail += STAT_POINTS_PER_LEVEL
                char.hp_max     += 10
                char.energy_max += 5
                char.hp_current  = char.hp_max
                leveled_up = True
                new_level  = char.level

            # Material drop on clear
            if cleared:
                mat_drop = try_drop_material(char.level)
                if mat_drop:
                    mats = dict(char.materials or {})
                    mats[mat_drop["id"]] = mats.get(mat_drop["id"], 0) + 1
                    char.materials = mats
                    flag_modified(char, "materials")

                # Track dungeon clears in achievements
                achs = dict(char.achievements or {})
                achs[f"cleared_{dungeon_id}"] = True
                # Check if all dungeons cleared
                if all(achs.get(f"cleared_{d['id']}") for d in _DUNGEONS):
                    unlock_achievement(char, "dungeon_master")
                unlock_achievement(char, "dungeon_clearer")
                char.achievements = achs
                flag_modified(char, "achievements")

            new_ach = check_achievements(char)
            await session.commit()

        if fled:
            embed = discord.Embed(
                title="🏃  撤退",
                description=(
                    f"從迷宮中撤退。\n"
                    f"保留獎勵：**{exp_gain}** EXP  │  💰 **{credits_gain:,}**"
                ),
                color=C_WARNING,
            )
        else:
            embed = _dungeon_clear_embed(
                dungeon or {"name": "迷宮", "emoji": "🗺️",
                            "clear_bonus_exp": 0, "clear_bonus_credits": 0},
                char_name, exp_gain, credits_gain, leveled_up, new_level, new_ach,
            )

        if followup:
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            try:
                await interaction.response.edit_message(embed=embed, view=None)
            except Exception:
                await interaction.followup.send(embed=embed, ephemeral=True)


def setup(bot: discord.Bot) -> None:
    bot.add_cog(DungeonCog(bot))
