import json
import random
from pathlib import Path

import discord
from discord.ext import commands
from sqlalchemy import select

from database.session import AsyncSessionFactory
from models.character import Character
from models.player import Player
from services.equipment_service import get_items_by_tier
from services.quest_service import update_quest_progress
from utils.embeds import C_DANGER, C_INFO, C_PRIMARY, C_WARNING, error_embed

_INVENTORY_LIMIT = 20
_LOCATIONS_PATH  = Path(__file__).parent.parent / "data" / "locations" / "locations.json"

with open(_LOCATIONS_PATH, encoding="utf-8") as _f:
    _LOCATIONS: list[dict] = json.load(_f)

_LOC_BY_NAME: dict[str, dict] = {loc["name"]: loc for loc in _LOCATIONS}
_LOC_BY_ID:   dict[str, dict] = {loc["id"]:   loc for loc in _LOCATIONS}


def _current_location(char: Character) -> dict:
    return _LOC_BY_NAME.get(char.current_location) or _LOCATIONS[0]


def _pick_event(location: dict) -> dict:
    events  = location["events"]
    weights = [e["weight"] for e in events]
    return random.choices(events, weights=weights, k=1)[0]


def _explore_embed(
    char: Character,
    location: dict,
    event: dict,
    extra: str = "",
    drop_name: str = "",
    color: int = C_INFO,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"{location['emoji']}  {location['name']}  ─  {event['title']}",
        description=f"{event['text']}\n\n{extra}".strip(),
        color=color,
    )
    if drop_name:
        embed.add_field(name="📦 獲得物品", value=drop_name, inline=False)
    embed.set_footer(text=f"Lv.{char.level} {char.name}  │  📍 {char.current_location}")
    return embed


class ExplorationCog(commands.Cog):
    def __init__(self, bot: discord.Bot) -> None:
        self.bot = bot

    @discord.slash_command(name="explore", description="🔍 在當前地點探索，尋找物資或危機")
    async def explore(self, ctx: discord.ApplicationContext) -> None:
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
                return await ctx.respond(embed=error_embed("無法在戰鬥中探索！"), ephemeral=True)
            if char.hp_current <= 0:
                return await ctx.respond(embed=error_embed("HP 歸零，無法行動。使用 `/rest`。"), ephemeral=True)

            location = _current_location(char)
            event    = _pick_event(location)
            etype    = event["type"]

            extra     = ""
            drop_name = ""
            color     = C_INFO

            if etype == "treasure":
                credits = random.randint(event["credits_min"], event["credits_max"])
                char.credits += credits
                extra = f"💰 獲得 **{credits:,}** 信用點！"
                color = C_PRIMARY

            elif etype == "trap":
                loss = max(1, int(char.hp_max * event["hp_loss_pct"]))
                char.hp_current = max(1, char.hp_current - loss)
                extra = f"❤️ 失去 **{loss}** HP！（剩餘 {char.hp_current} / {char.hp_max}）"
                color = C_DANGER

            elif etype == "heal":
                restore = max(1, int(char.hp_max * event["hp_restore_pct"]))
                char.hp_current = min(char.hp_max, char.hp_current + restore)
                extra = f"❤️ 恢復 **{restore}** HP！（現在 {char.hp_current} / {char.hp_max}）"
                color = C_PRIMARY

            elif etype == "item":
                tier  = event.get("tier", 1)
                pool  = get_items_by_tier(tier)
                inv   = list(char.inventory or [])
                if pool and len(inv) < _INVENTORY_LIMIT:
                    item = random.choice(pool)
                    inv.append(item["id"])
                    char.inventory = inv
                    bonus = f"+{item['atk_bonus']} ATK" if "atk_bonus" in item else f"+{item['def_bonus']} DEF"
                    drop_name = f"{item['emoji']} **{item['name']}** `{bonus}` 已加入背包"
                    color = C_PRIMARY
                    update_quest_progress(char, "loot_equipment", 1)
                elif not pool:
                    extra = "翻找了一番，什麼也沒找到。"
                else:
                    extra = "⚠️ 背包已滿，無法撿起物品！使用 `/inventory` 管理背包。"
                    color = C_WARNING

            elif etype == "nothing":
                color = C_WARNING

            update_quest_progress(char, "explore_times", 1)
            await session.commit()

        embed = _explore_embed(char, location, event, extra, drop_name, color)
        await ctx.respond(embed=embed)

    @discord.slash_command(name="travel", description="🗺️ 前往其他地點")
    async def travel(self, ctx: discord.ApplicationContext) -> None:
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
            return await ctx.respond(embed=error_embed("無法在戰鬥中移動！"), ephemeral=True)

        await ctx.respond(
            embed=_travel_embed(char),
            view=TravelView(char),
            ephemeral=True,
        )


def _travel_embed(char: Character) -> discord.Embed:
    lines = []
    for loc in _LOCATIONS:
        unlocked = char.level >= loc["required_level"]
        status   = "✅" if unlocked else f"🔒 需 Lv.{loc['required_level']}"
        current  = "  ◀ 目前位置" if loc["name"] == char.current_location else ""
        lines.append(
            f"{loc['emoji']} **{loc['name']}**  {status}{current}\n"
            f"> {loc['desc']}"
        )
    embed = discord.Embed(
        title="🗺️  移動至其他地點",
        description="\n\n".join(lines),
        color=C_INFO,
    )
    embed.set_footer(text=f"目前位置：{char.current_location}  │  Lv.{char.level} {char.name}")
    return embed


class TravelSelect(discord.ui.Select):
    def __init__(self, char: Character) -> None:
        options = []
        for loc in _LOCATIONS:
            unlocked = char.level >= loc["required_level"]
            options.append(
                discord.SelectOption(
                    label=loc["name"],
                    value=loc["name"],
                    emoji=loc["emoji"],
                    description=f"需 Lv.{loc['required_level']}  ·  {loc['desc'][:30]}",
                    default=(loc["name"] == char.current_location),
                )
            )
        super().__init__(placeholder="選擇目的地...", options=options, min_values=1, max_values=1)
        self.char_id         = char.id
        self.discord_user_id = char.id   # carried for access check in view

    async def callback(self, interaction: discord.Interaction) -> None:
        destination = self.values[0]
        loc = _LOC_BY_NAME.get(destination)
        if not loc:
            return await interaction.response.send_message("未知地點。", ephemeral=True)

        async with AsyncSessionFactory() as session:
            result = await session.execute(select(Character).where(Character.id == self.char_id))
            char   = result.scalar_one()

            if char.level < loc["required_level"]:
                return await interaction.response.send_message(
                    f"需要達到 **Lv.{loc['required_level']}** 才能前往 {loc['emoji']} **{loc['name']}**。",
                    ephemeral=True,
                )

            if char.current_location == destination:
                return await interaction.response.send_message(
                    f"你已經在 **{destination}** 了。", ephemeral=True
                )

            char.current_location = destination
            update_quest_progress(char, "travel_times", 1)
            await session.commit()
            await session.refresh(char)

        await interaction.response.edit_message(
            embed=_travel_embed(char),
            view=TravelView(char),
        )
        await interaction.followup.send(
            embed=discord.Embed(
                description=f"✅  已抵達 {loc['emoji']} **{loc['name']}**。",
                color=C_PRIMARY,
            ),
            ephemeral=True,
        )


class TravelView(discord.ui.View):
    def __init__(self, char: Character) -> None:
        super().__init__(timeout=120)
        self.add_item(TravelSelect(char))


def setup(bot: discord.Bot) -> None:
    bot.add_cog(ExplorationCog(bot))
