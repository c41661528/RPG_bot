from __future__ import annotations

import discord
from discord.ext import bridge, commands
from sqlalchemy import select

from config import MAX_LEVEL, STAT_POINTS_PER_LEVEL, exp_for_next_level
from database.session import AsyncSessionFactory
from models.character import Character
from models.player import Player
from services.pvp_service import (
    DUEL_DAILY_LIMIT,
    calc_rewards, can_duel, duels_today,
    player_combat_stats, record_duel, simulate_duel,
)
from services.title_service import check_title_unlocks
from utils.embeds import C_DANGER, C_INFO, C_PRIMARY, C_WARNING, error_embed


def _challenge_embed(challenger: Character, target: discord.User) -> discord.Embed:
    return discord.Embed(
        title="⚔️  決鬥邀請",
        description=(
            f"**{challenger.name}** (Lv.{challenger.level}) 向 {target.mention} 發起決鬥！\n\n"
            f"⏳ 60 秒內回應，逾時自動拒絕。"
        ),
        color=C_WARNING,
    )


def _result_embed(
    winner: dict, loser: dict, logs: list[str],
    cred: int, exp: int, leveled_up: bool, new_level: int,
    new_titles: list[str],
) -> discord.Embed:
    desc_lines = [
        f"🏆  **{winner['name']}** 擊敗了 **{loser['name']}**！",
        f"💰 +{cred:,}　🎖️ +{exp} EXP",
    ]
    if leveled_up:
        desc_lines.append(f"🎉 升級至 **Lv.{new_level}**！")
    if new_titles:
        desc_lines.append(f"🎖️ 新稱號：" + "、".join(new_titles))
    desc_lines += [
        "",
        "─────── 戰鬥紀錄（最後 8 回合） ───────",
    ] + [f"> {l}" for l in logs[-8:]]
    return discord.Embed(
        title=f"⚔️  決鬥結果  —  {winner['name']} vs {loser['name']}",
        description="\n".join(desc_lines),
        color=C_PRIMARY,
    )


class _DuelView(discord.ui.View):
    def __init__(
        self,
        challenger_char_id: int,
        target_user_id: int,
        challenger_user_id: int,
    ) -> None:
        super().__init__(timeout=60)
        self.challenger_char_id = challenger_char_id
        self.target_user_id     = target_user_id
        self.challenger_user_id = challenger_user_id
        self._handled = False

    @discord.ui.button(label="接受決鬥", emoji="✅", style=discord.ButtonStyle.success)
    async def accept(self, button: discord.ui.Button, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.target_user_id:
            return await interaction.response.send_message("這場決鬥與你無關。", ephemeral=True)
        if self._handled:
            return
        self._handled = True

        # ── Snapshot both characters ─────────────────────────────
        async with AsyncSessionFactory() as session:
            ch = (await session.execute(
                select(Character).where(Character.id == self.challenger_char_id)
            )).scalar_one_or_none()
            tg = (await session.execute(
                select(Character).join(Player, Character.player_id == Player.id)
                .where(Player.discord_id == self.target_user_id)
            )).scalar_one_or_none()

            if ch is None or tg is None:
                return await interaction.response.edit_message(
                    embed=error_embed("找不到角色資料。"), view=None,
                )
            ok1, r1 = can_duel(ch)
            ok2, r2 = can_duel(tg)
            if not ok1:
                return await interaction.response.edit_message(
                    embed=error_embed(f"挑戰者狀態異常：{r1}"), view=None,
                )
            if not ok2:
                return await interaction.response.edit_message(
                    embed=error_embed(f"你的狀態異常：{r2}"), view=None,
                )
            p1 = player_combat_stats(ch)
            p2 = player_combat_stats(tg)

        # ── Simulate (outside session) ───────────────────────────
        winner, loser, logs = simulate_duel(p1, p2)

        # ── Apply rewards ────────────────────────────────────────
        async with AsyncSessionFactory() as session:
            ch = (await session.execute(
                select(Character).where(Character.id == self.challenger_char_id)
            )).scalar_one()
            tg = (await session.execute(
                select(Character).join(Player, Character.player_id == Player.id)
                .where(Player.discord_id == self.target_user_id)
            )).scalar_one()

            winner_char = ch if winner["char_id"] == ch.id else tg
            loser_char  = tg if winner_char is ch else ch

            cred, exp = calc_rewards(winner_char.level, loser_char.level, loser_char.credits)
            transfer  = min(cred, max(0, loser_char.credits))

            loser_char.credits  -= transfer
            winner_char.credits += transfer
            winner_char.exp     += exp

            leveled_up = False
            new_level  = winner_char.level
            while winner_char.exp >= exp_for_next_level(winner_char.level) and winner_char.level < MAX_LEVEL:
                winner_char.exp   -= exp_for_next_level(winner_char.level)
                winner_char.level += 1
                winner_char.stat_points_avail += STAT_POINTS_PER_LEVEL
                winner_char.hp_max      += 10
                winner_char.energy_max  += 5
                winner_char.hp_current   = winner_char.hp_max
                leveled_up = True
                new_level  = winner_char.level

            record_duel(winner_char, won=True)
            record_duel(loser_char,  won=False)
            new_titles_w = check_title_unlocks(winner_char)
            check_title_unlocks(loser_char)

            await session.commit()

        await interaction.response.edit_message(
            embed=_result_embed(
                winner, loser, logs, transfer, exp,
                leveled_up, new_level, new_titles_w,
            ),
            view=None,
        )

    @discord.ui.button(label="拒絕", emoji="❌", style=discord.ButtonStyle.secondary)
    async def decline(self, button: discord.ui.Button, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.target_user_id:
            return await interaction.response.send_message("這場決鬥與你無關。", ephemeral=True)
        if self._handled:
            return
        self._handled = True
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="❌  決鬥被拒絕",
                description="對手婉拒了挑戰。",
                color=C_DANGER,
            ),
            view=None,
        )

    async def on_timeout(self) -> None:
        for c in self.children:
            c.disabled = True


class PvPCog(commands.Cog):
    def __init__(self, bot: discord.Bot) -> None:
        self.bot = bot

    @bridge.bridge_command(name="duel", description="⚔️ 向其他玩家發起 PvP 決鬥")
    async def duel(
        self,
        ctx: discord.ApplicationContext,
        opponent: bridge.BridgeOption(discord.Member, description="要挑戰的玩家"),
    ) -> None:
        if opponent.id == ctx.author.id:
            return await ctx.respond(embed=error_embed("不能跟自己決鬥。"), ephemeral=True)
        if opponent.bot:
            return await ctx.respond(embed=error_embed("不能挑戰機器人。"), ephemeral=True)

        async with AsyncSessionFactory() as session:
            ch = (await session.execute(
                select(Character).join(Player, Character.player_id == Player.id)
                .where(Player.discord_id == ctx.author.id)
            )).scalar_one_or_none()
            tg = (await session.execute(
                select(Character).join(Player, Character.player_id == Player.id)
                .where(Player.discord_id == opponent.id)
            )).scalar_one_or_none()

        if ch is None:
            return await ctx.respond(embed=error_embed("尚未建立角色。"), ephemeral=True)
        if tg is None:
            return await ctx.respond(
                embed=error_embed(f"{opponent.display_name} 尚未建立角色。"),
                ephemeral=True,
            )
        ok, reason = can_duel(ch)
        if not ok:
            return await ctx.respond(embed=error_embed(reason), ephemeral=True)

        view = _DuelView(ch.id, opponent.id, ctx.author.id)
        await ctx.respond(
            content=opponent.mention,
            embed=_challenge_embed(ch, opponent),
            view=view,
        )

    @bridge.bridge_command(name="pvp_stats", description="⚔️ 查看 PvP 戰績")
    async def pvp_stats(self, ctx: discord.ApplicationContext) -> None:
        async with AsyncSessionFactory() as session:
            char = (await session.execute(
                select(Character).join(Player, Character.player_id == Player.id)
                .where(Player.discord_id == ctx.author.id)
            )).scalar_one_or_none()
        if char is None:
            return await ctx.respond(embed=error_embed("尚未建立角色。"), ephemeral=True)

        s      = char.pvp_stats or {}
        wins   = s.get("wins", 0)
        losses = s.get("losses", 0)
        total  = wins + losses
        rate   = (wins / total * 100) if total else 0

        embed = discord.Embed(
            title=f"⚔️  PvP 戰績  —  {char.name}",
            description=(
                f"🏆 勝場：**{wins}**\n"
                f"💀 敗場：**{losses}**\n"
                f"📊 勝率：**{rate:.1f}%**\n\n"
                f"今日決鬥：{duels_today(char)} / {DUEL_DAILY_LIMIT}"
            ),
            color=C_INFO,
        )
        await ctx.respond(embed=embed, ephemeral=True)


def setup(bot: discord.Bot) -> None:
    bot.add_cog(PvPCog(bot))
