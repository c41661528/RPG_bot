import discord
from discord.ext import commands
from sqlalchemy import select

from config import MAX_LEVEL, STAT_POINTS_PER_LEVEL, exp_for_next_level
from database.session import AsyncSessionFactory
from models.character import Character
from models.player import Player
from services.achievement_service import check_achievements, unlock_achievement
from services.quest_service import (
    ensure_daily_quests,
    ensure_weekly_quests,
    update_quest_progress,
)
from utils.embeds import C_INFO, C_PRIMARY, C_WARNING, error_embed

_BAR_LEN = 8


def _progress_bar(current: int, target: int) -> str:
    filled = round(_BAR_LEN * current / target) if target else _BAR_LEN
    return "█" * filled + "░" * (_BAR_LEN - filled)


def _quest_embed(char: Character, quests: list[dict], mode: str = "daily") -> discord.Embed:
    lines: list[str] = []
    all_claimed = all(q["claimed"] for q in quests)

    for i, q in enumerate(quests, 1):
        if q["claimed"]:
            status = "✅ 已領取"
        elif q["completed"]:
            status = "🎁 可領取"
        else:
            status = f"`{_progress_bar(q['progress'], q['target'])}` {q['progress']}/{q['target']}"

        lines.append(
            f"{q['icon']} **{q['desc']}**\n"
            f"> {status}　│　獎勵：**{q['reward_exp']}** EXP + **{q['reward_credits']:,}** 💰"
        )

    title_prefix = "📋 每日任務" if mode == "daily" else "📅 週常任務"
    reset_text   = "每日 0 點重置" if mode == "daily" else "每週一 0 點重置"
    color = C_PRIMARY if all_claimed else C_INFO
    embed = discord.Embed(
        title=f"{title_prefix}  —  {char.name}",
        description="\n\n".join(lines),
        color=color,
    )
    embed.set_footer(text=f"{reset_text}  │  完成任務後點擊「領取獎勵」")
    return embed


class ClaimView(discord.ui.View):
    def __init__(self, char: Character, discord_user_id: int, mode: str = "daily") -> None:
        super().__init__(timeout=120)
        self.char_id         = char.id
        self.discord_user_id = discord_user_id
        self.mode            = mode

        quests_src = (char.quests or {}).get("quests", []) if mode == "daily" \
                     else (char.weekly_quests or {}).get("quests", [])
        has_claimable = any(q["completed"] and not q["claimed"] for q in quests_src)
        self.children[0].disabled = not has_claimable

    @discord.ui.button(label="領取所有獎勵", emoji="🎁", style=discord.ButtonStyle.success)
    async def claim(self, button: discord.ui.Button, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.discord_user_id:
            return await interaction.response.send_message("這不是你的面板！", ephemeral=True)

        mode = self.mode

        async with AsyncSessionFactory() as session:
            result = await session.execute(select(Character).where(Character.id == self.char_id))
            char   = result.scalar_one()

            if mode == "daily":
                from services.quest_service import ensure_daily_quests
                quests = list((char.quests or {}).get("quests", []))
                save_key = "quests"
                from datetime import date
                save_val = {"date": str(date.today()), "quests": quests}
            else:
                from datetime import date
                from services.quest_service import _iso_week
                quests = list((char.weekly_quests or {}).get("quests", []))
                save_key = "weekly_quests"
                save_val = {"week": _iso_week(date.today()), "quests": quests}

            total_exp  = 0
            total_cred = 0
            leveled_up = False
            new_level  = char.level
            claimed_any = False

            for q in quests:
                if q["completed"] and not q["claimed"]:
                    q["claimed"]    = True
                    total_exp      += q["reward_exp"]
                    total_cred     += q["reward_credits"]
                    claimed_any     = True

            if not claimed_any:
                return await interaction.response.send_message("沒有可領取的獎勵。", ephemeral=True)

            char.exp     += total_exp
            char.credits += total_cred

            while char.exp >= exp_for_next_level(char.level) and char.level < MAX_LEVEL:
                char.exp -= exp_for_next_level(char.level)
                char.level += 1
                char.stat_points_avail += STAT_POINTS_PER_LEVEL
                char.hp_max     += 10
                char.energy_max += 5
                char.hp_current  = char.hp_max
                leveled_up = True
                new_level  = char.level

            from sqlalchemy.orm.attributes import flag_modified
            save_val["quests"] = quests
            setattr(char, save_key, save_val)
            flag_modified(char, save_key)

            # Achievement: completing first daily quest
            if mode == "daily":
                unlock_achievement(char, "quest_starter")
            # Achievement: all 3 weekly quests claimed
            if mode == "weekly" and all(q["claimed"] for q in quests):
                unlock_achievement(char, "weekly_hero")

            new_ach = check_achievements(char)
            await session.commit()
            await session.refresh(char)

        level_txt = (
            f"\n\n🎉 **升級！Lv.{new_level}** 獲得 {STAT_POINTS_PER_LEVEL} 屬性點！"
            if leveled_up else ""
        )
        ach_txt = ""
        if new_ach:
            ach_txt = "\n\n🏆 解鎖成就：" + "、".join(new_ach)

        button.disabled = True
        await interaction.response.edit_message(
            embed=_quest_embed(char, quests, mode),
            view=self,
        )
        await interaction.followup.send(
            embed=discord.Embed(
                description=(
                    f"✅  領取成功！獲得 **{total_exp}** EXP + **{total_cred:,}** 💰"
                    f"{level_txt}{ach_txt}"
                ),
                color=C_PRIMARY,
            ),
            ephemeral=True,
        )


class QuestsCog(commands.Cog):
    def __init__(self, bot: discord.Bot) -> None:
        self.bot = bot

    @discord.slash_command(name="quest", description="📋 查看今日每日任務")
    async def quest(self, ctx: discord.ApplicationContext) -> None:
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                select(Character)
                .join(Player, Character.player_id == Player.id)
                .where(Player.discord_id == ctx.author.id)
            )
            char = result.scalar_one_or_none()

            if char is None:
                return await ctx.respond(embed=error_embed("尚未建立角色。使用 `/start`。"), ephemeral=True)

            quests = ensure_daily_quests(char)
            await session.commit()

        view = ClaimView(char, ctx.author.id, mode="daily")
        await ctx.respond(embed=_quest_embed(char, quests, "daily"), view=view, ephemeral=True)

    @discord.slash_command(name="weekly_quest", description="📅 查看本週週常任務")
    async def weekly_quest(self, ctx: discord.ApplicationContext) -> None:
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                select(Character)
                .join(Player, Character.player_id == Player.id)
                .where(Player.discord_id == ctx.author.id)
            )
            char = result.scalar_one_or_none()

            if char is None:
                return await ctx.respond(embed=error_embed("尚未建立角色。使用 `/start`。"), ephemeral=True)

            quests = ensure_weekly_quests(char)
            await session.commit()

        view = ClaimView(char, ctx.author.id, mode="weekly")
        await ctx.respond(embed=_quest_embed(char, quests, "weekly"), view=view, ephemeral=True)


def setup(bot: discord.Bot) -> None:
    bot.add_cog(QuestsCog(bot))
