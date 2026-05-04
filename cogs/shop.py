import discord
from discord.ext import commands
from sqlalchemy import select

from config import ENERGY_CELL_COST, MEDKIT_COST
from database.session import AsyncSessionFactory
from models.character import Character
from models.player import Player
from services.quest_service import update_quest_progress
from utils.embeds import C_INFO, error_embed, success_embed


def _shop_embed(char: Character) -> discord.Embed:
    embed = discord.Embed(
        title="🏪  黑市補給站",
        description=(
            "在廢墟邊緣的昏暗小隔間，一個蒙面商人向你招手。\n\n"
            f"💰 **你的信用點：** {char.credits:,}\n"
            f"🩹 **急救包：** {char.medkits} 個\n"
            f"🔋 **能量電池：** {char.energy_cells} 個"
        ),
        color=C_INFO,
    )
    embed.add_field(
        name=f"🩹 急救包　{MEDKIT_COST:,} 💰",
        value="戰鬥中使用，恢復 **35%** 最大 HP。",
        inline=True,
    )
    embed.add_field(
        name=f"🔋 能量電池　{ENERGY_CELL_COST:,} 💰",
        value="戰鬥中使用，恢復 **40** 能量。",
        inline=True,
    )
    embed.set_footer(text="使用 /buy 購買道具")
    return embed


class ShopCog(commands.Cog):
    def __init__(self, bot: discord.Bot) -> None:
        self.bot = bot

    @discord.slash_command(name="shop", description="🏪 查看黑市商店")
    async def shop(self, ctx: discord.ApplicationContext) -> None:
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                select(Character)
                .join(Player, Character.player_id == Player.id)
                .where(Player.discord_id == ctx.author.id)
            )
            char = result.scalar_one_or_none()

        if char is None:
            return await ctx.respond(embed=error_embed("尚未建立角色。使用 `/start`。"), ephemeral=True)

        await ctx.respond(embed=_shop_embed(char), ephemeral=True)

    @discord.slash_command(name="buy", description="🛒 購買道具")
    async def buy(
        self,
        ctx: discord.ApplicationContext,
        item: discord.Option(
            str,
            description="道具名稱",
            choices=["急救包", "能量電池"],
        ),
        quantity: discord.Option(
            int,
            description="購買數量（預設 1）",
            min_value=1,
            max_value=10,
            default=1,
        ),
    ) -> None:
        if item == "急救包":
            cost_each = MEDKIT_COST
            attr      = "medkits"
            emoji     = "🩹"
        else:
            cost_each = ENERGY_CELL_COST
            attr      = "energy_cells"
            emoji     = "🔋"

        total_cost = cost_each * quantity

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
            if char.is_in_combat:
                return await ctx.respond(embed=error_embed("無法在戰鬥中購物！"), ephemeral=True)
            if char.credits < total_cost:
                return await ctx.respond(
                    embed=error_embed(
                        f"信用點不足。需要 **{total_cost:,}** 💰（現有：{char.credits:,}）。"
                    ),
                    ephemeral=True,
                )

            char.credits -= total_cost
            setattr(char, attr, getattr(char, attr) + quantity)
            new_count = getattr(char, attr)
            update_quest_progress(char, "buy_items", quantity)
            await session.commit()

        remaining = char.credits  # already decremented in the session
        await ctx.respond(
            embed=success_embed(
                f"購買了 **{quantity}** 個 {emoji} **{item}**，花費 **{total_cost:,}** 💰\n"
                f"現有存量：**{new_count}** 個　│　剩餘信用點：**{remaining:,}**"
            ),
            ephemeral=True,
        )


def setup(bot: discord.Bot) -> None:
    bot.add_cog(ShopCog(bot))
