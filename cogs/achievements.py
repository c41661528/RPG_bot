import discord
from discord.ext import bridge, commands
from sqlalchemy import select

from database.session import AsyncSessionFactory
from models.character import Character
from models.player import Player
from services.achievement_service import all_achievements
from utils.embeds import C_INFO, C_PRIMARY, C_WARNING, error_embed

_LOCK_EMOJI = "🔒"


def _achievements_embed(char: Character) -> discord.Embed:
    achs_owned = char.achievements or {}
    all_ach    = all_achievements()

    unlocked = [a for a in all_ach if achs_owned.get(a["id"])]
    locked   = [a for a in all_ach if not achs_owned.get(a["id"])]

    unlocked_lines = [
        f"{a['emoji']} **{a['name']}**  —  {a['desc']}"
        for a in unlocked
    ] or ["`尚未解鎖任何成就`"]

    locked_lines = [
        f"{_LOCK_EMOJI} ~~{a['name']}~~  —  {a['desc']}"
        for a in locked
    ]

    total   = len(all_ach)
    count   = len(unlocked)
    pct     = int(count / total * 100) if total else 0
    bar_len = 10
    filled  = round(bar_len * count / total) if total else 0
    bar     = "█" * filled + "░" * (bar_len - filled)

    color = C_PRIMARY if count == total else C_INFO

    embed = discord.Embed(
        title=f"🏆  成就  —  {char.name}",
        description=f"`{bar}` **{count}/{total}** 已解鎖  （{pct}%）",
        color=color,
    )
    embed.add_field(
        name="✅ 已解鎖",
        value="\n".join(unlocked_lines),
        inline=False,
    )
    if locked_lines:
        embed.add_field(
            name="🔒 未解鎖",
            value="\n".join(locked_lines[:15]),  # cap to avoid embed limit
            inline=False,
        )
    embed.set_footer(text="成就在遊戲中自動解鎖  ·  完成條件即可獲得")
    return embed


class AchievementsCog(commands.Cog):
    def __init__(self, bot: discord.Bot) -> None:
        self.bot = bot

    @bridge.bridge_command(name="achievements", description="🏆 查看所有成就進度")
    async def achievements(self, ctx: discord.ApplicationContext) -> None:
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                select(Character)
                .join(Player, Character.player_id == Player.id)
                .where(Player.discord_id == ctx.author.id)
            )
            char = result.scalar_one_or_none()

        if char is None:
            return await ctx.respond(
                embed=error_embed("尚未建立角色。使用 `/start`。"), ephemeral=True
            )

        await ctx.respond(embed=_achievements_embed(char), ephemeral=True)


def setup(bot: discord.Bot) -> None:
    bot.add_cog(AchievementsCog(bot))
