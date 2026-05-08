import discord
from discord.ext import bridge, commands
from sqlalchemy import select

from config import SHOP_ITEMS, SHOP_ITEMS_BY_NAME
from database.session import AsyncSessionFactory
from models.character import Character
from models.player import Player
from services.quest_service import update_quest_progress
from utils.embeds import C_INFO, error_embed, success_embed


def _item_stock(char: Character, item_id: str) -> int:
    if item_id == "medkit":
        return char.medkits
    if item_id == "energy_cell":
        return char.energy_cells
    return (char.consumables or {}).get(item_id, 0)


def _shop_embed(char: Character) -> discord.Embed:
    embed = discord.Embed(
        title="🏪  黑市補給站",
        description=(
            "在廢墟邊緣的昏暗小隔間，一個蒙面商人向你招手。\n\n"
            f"💰 **你的信用點：** {char.credits:,}"
        ),
        color=C_INFO,
    )

    recovery = [i for i in SHOP_ITEMS if i["category"] == "recovery"]
    combat   = [i for i in SHOP_ITEMS if i["category"] == "combat"]

    def _fmt(items: list[dict]) -> str:
        lines = []
        for item in items:
            stock = _item_stock(char, item["id"])
            lines.append(
                f"{item['emoji']} **{item['name']}**　{item['cost']:,} 💰　`×{stock}`\n"
                f"　{item['desc']}"
            )
        return "\n".join(lines)

    embed.add_field(name="🩹 回復補給", value=_fmt(recovery), inline=False)
    embed.add_field(name="⚔️ 戰鬥用品", value=_fmt(combat),   inline=False)
    embed.set_footer(text="使用 /buy <道具名稱> [數量] 購買道具，最多一次 10 個")
    return embed


class ShopCog(commands.Cog):
    def __init__(self, bot: discord.Bot) -> None:
        self.bot = bot

    @bridge.bridge_command(name="shop", description="🏪 查看黑市商店")
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

    @bridge.bridge_command(name="buy", description="🛒 購買道具")
    async def buy(
        self,
        ctx: discord.ApplicationContext,
        item: discord.Option(
            str,
            description="道具名稱",
            choices=[i["name"] for i in SHOP_ITEMS],
        ),
        quantity: discord.Option(
            int,
            description="購買數量（預設 1）",
            min_value=1,
            max_value=10,
            default=1,
        ),
    ) -> None:
        item_info  = SHOP_ITEMS_BY_NAME[item]
        total_cost = item_info["cost"] * quantity

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
            item_id = item_info["id"]

            if item_id == "medkit":
                char.medkits += quantity
                new_count = char.medkits
            elif item_id == "energy_cell":
                char.energy_cells += quantity
                new_count = char.energy_cells
            else:
                cons = dict(char.consumables or {})
                cons[item_id] = cons.get(item_id, 0) + quantity
                char.consumables = cons
                new_count = cons[item_id]

            update_quest_progress(char, "buy_items", quantity)
            await session.commit()

        await ctx.respond(
            embed=success_embed(
                f"購買了 **{quantity}** 個 {item_info['emoji']} **{item}**，"
                f"花費 **{total_cost:,}** 💰\n"
                f"現有存量：**{new_count}** 個　│　剩餘信用點：**{char.credits:,}**"
            ),
            ephemeral=True,
        )


def setup(bot: discord.Bot) -> None:
    bot.add_cog(ShopCog(bot))
